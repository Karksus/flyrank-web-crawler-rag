import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
from cachetools import TTLCache
from tldextract import extract

from app.core.config import settings
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

PULLPUSH_BASE_URL = "https://api.pullpush.io"
REDDIT_RSS_SEARCH_URL = "https://www.reddit.com/search.rss"
BRAVE_SEARCH_URL = "https://search.brave.com/search"
HACKER_NEWS_API_URL = "https://hn.algolia.com/api/v1/search"
BING_NEWS_RSS_URL = "https://www.bing.com/news/search"

GENERIC_COMPANY_TOKENS = {
    "bot", "company", "corp", "corporation", "group", "inc", "limited", "llc",
    "ltd", "plc",
}


def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def _iso_from_timestamp(timestamp: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _iso_from_rss_date(value: str) -> Optional[str]:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _subreddit_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


class PublicOpinionService:
    """Collect public mentions about a company from free public sources.

    Reddit's public JSON endpoints are frequently blocked for unauthenticated
    server-to-server requests, so Reddit is searched through its public RSS
    feed first. A public web-search fallback covers rate limits, and PullPush
    is a last-resort archive. Hacker News uses the Algolia API, and news uses
    Bing News RSS.
    """

    def __init__(self):
        self.timeout = settings.PUBLIC_OPINION_TIMEOUT
        self.max_items = settings.PUBLIC_OPINION_MAX_ITEMS
        self.user_agent = settings.PUBLIC_OPINION_USER_AGENT
        self.cache: TTLCache = TTLCache(
            maxsize=256,
            ttl=max(60, settings.PUBLIC_OPINION_CACHE_TTL_SECONDS),
        )

    def _company_terms(self, company_name: str, domain: str) -> Dict[str, Any]:
        extracted = extract(domain or "")
        domain_label = (extracted.domain or (domain or "").split(".")[0]).lower()
        clean_name = re.sub(r"\s+bot\s*$", "", company_name or "", flags=re.IGNORECASE).strip()

        # If the stored name is just the domain, prefer the readable domain label.
        if not clean_name or "." in clean_name and " " not in clean_name:
            display_name = domain_label or clean_name
        else:
            display_name = clean_name

        query = domain_label or display_name
        name_query = clean_name if clean_name and " " in clean_name else query

        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", (clean_name or "").lower())
            if len(token) >= 3 and token not in GENERIC_COMPANY_TOKENS
        }
        if domain_label:
            tokens.add(domain_label)
        if not tokens:
            tokens = {query.lower()}

        return {
            "display_name": display_name,
            "query": query,
            "name_query": name_query,
            "tokens": tokens,
        }

    def _matches(self, text: str, tokens: Iterable[str]) -> bool:
        haystack = (text or "").lower()
        return any(token and token in haystack for token in tokens)

    async def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        ) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def _get_text(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*;q=0.8",
            },
        ) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text

    async def _get_html(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text

    def _subreddit_candidates(self, company_name: str, domain_label: str) -> List[str]:
        clean_name = re.sub(
            r"\s+bot\s*$", "", company_name or "", flags=re.IGNORECASE
        ).strip()
        candidates: List[str] = []
        for candidate in (
            _subreddit_slug(clean_name),
            _subreddit_slug(domain_label),
            domain_label.replace(".", ""),
        ):
            candidate = candidate.lower().strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    async def _lookup_subreddit(
        self, company_name: str, domain_label: str
    ) -> Optional[Dict[str, Any]]:
        """Best-effort check for a dedicated subreddit."""
        # Reddit blocks anonymous JSON requests from many server IPs. Try one
        # request and fall back quietly if the network denies it.
        for candidate in self._subreddit_candidates(company_name, domain_label)[:2]:
            url = f"https://www.reddit.com/r/{candidate}/about.json"
            try:
                async with httpx.AsyncClient(
                    timeout=min(5, self.timeout),
                    follow_redirects=True,
                    headers={"User-Agent": self.user_agent},
                ) as client:
                    response = await client.get(url)
                if response.status_code == 404:
                    continue
                if response.status_code in (401, 403, 429):
                    logger.info(
                        "Reddit subreddit lookup blocked (HTTP %s); using archive fallback",
                        response.status_code,
                    )
                    break
                if response.status_code != 200:
                    continue
                payload = response.json()
                data = payload.get("data") or {}
                if not data.get("display_name"):
                    continue
                return {
                    "name": data.get("display_name"),
                    "title": data.get("title"),
                    "subscribers": data.get("subscribers"),
                    "url": f"https://www.reddit.com{data.get('url', '')}",
                    "description": (data.get("public_description") or "")[:300],
                }
            except Exception:
                logger.debug("Reddit subreddit lookup failed for %s", candidate, exc_info=True)
                break

        return None

    async def _pullpush_submissions(
        self,
        params: Dict[str, Any],
        tokens: Iterable[str],
        require_match: bool = True,
    ) -> List[Dict[str, Any]]:
        query_params = {
            **params,
            "size": 25,
            "sort": "desc",
            "sort_type": "score",
        }
        payload = await self._get_json(
            f"{PULLPUSH_BASE_URL}/reddit/search/submission/", query_params
        )
        posts: List[Dict[str, Any]] = []
        for post in payload.get("data") or []:
            title = (post.get("title") or "").strip()
            selftext = (post.get("selftext") or "").strip()
            text = f"{title} {selftext}"
            if require_match and not self._matches(text, tokens):
                continue
            if selftext in ("[removed]", "[deleted]"):
                selftext = ""

            subreddit = post.get("subreddit") or "Reddit"
            permalink = post.get("permalink") or ""
            url = f"https://www.reddit.com{permalink}" if permalink else post.get("url")
            if not url:
                continue

            posts.append({
                "source": "reddit",
                "source_label": f"r/{subreddit}",
                "title": title or "Reddit discussion",
                "url": url,
                "snippet": (selftext or title)[:300],
                "score": int(post.get("score") or 0),
                "comments": int(post.get("num_comments") or 0),
                "created_at": _iso_from_timestamp(post.get("created_utc")),
                "author": post.get("author"),
                "_post_id": post.get("id"),
                "_subreddit": subreddit,
            })
        return posts

    async def _pullpush_comments(
        self, post_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        if not post_id:
            return []
        payload = await self._get_json(
            f"{PULLPUSH_BASE_URL}/reddit/search/comment/",
            {
                "link_id": f"t3_{post_id}",
                "size": limit,
                "sort": "desc",
                "sort_type": "score",
            },
        )
        comments: List[Dict[str, Any]] = []
        for comment in (payload.get("data") or [])[:3]:
            body = (comment.get("body") or "").strip()
            if not body or body in ("[removed]", "[deleted]"):
                continue
            subreddit = comment.get("subreddit") or "Reddit"
            permalink = comment.get("permalink") or ""
            if not permalink:
                continue
            comments.append({
                "source": "reddit",
                "source_label": f"r/{subreddit} comment",
                "title": body[:120],
                "url": f"https://www.reddit.com{permalink}",
                "snippet": body[:300],
                "score": int(comment.get("score") or 0),
                "comments": 0,
                "created_at": _iso_from_timestamp(comment.get("created_utc")),
                "author": comment.get("author"),
            })
        return comments

    async def _reddit_rss_items(
        self, query: str, tokens: Iterable[str]
    ) -> List[Dict[str, Any]]:
        """Search Reddit through its public Atom feed.

        The anonymous Reddit JSON endpoints are often blocked from server IPs,
        while the public search feed is intended for feed readers and does not
        require credentials.
        """
        xml_text = await self._get_text(
            REDDIT_RSS_SEARCH_URL,
            {"q": query, "sort": "relevance", "t": "all"},
        )
        root = ET.fromstring(xml_text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items: List[Dict[str, Any]] = []

        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            link = entry.find("a:link", ns)
            url = (link.attrib.get("href") if link is not None else "") or ""
            if not title or not url:
                continue
            if url.startswith("/"):
                url = f"https://www.reddit.com{url}"

            content = _strip_html(
                entry.findtext("a:content", default="", namespaces=ns) or ""
            )
            # Reddit appends boilerplate after the post body in its feed.
            content = re.split(
                r"\bsubmitted by\b", content, maxsplit=1, flags=re.IGNORECASE
            )[0].strip()

            category = entry.find("a:category", ns)
            subreddit = ""
            if category is not None:
                subreddit = (
                    category.attrib.get("term")
                    or category.attrib.get("label")
                    or ""
                ).strip()
                subreddit = re.sub(r"^/?r/", "", subreddit, flags=re.IGNORECASE)

            if not self._matches(f"{title} {content} {url}", tokens):
                continue

            author = (
                entry.findtext("a:author/a:name", default="", namespaces=ns) or ""
            ).strip()
            author = re.sub(r"^/?u/", "", author, flags=re.IGNORECASE)
            published = (
                entry.findtext("a:published", default="", namespaces=ns)
                or entry.findtext("a:updated", default="", namespaces=ns)
            )
            post_id_match = re.search(r"/comments/([a-z0-9]+)", url, flags=re.IGNORECASE)

            items.append({
                "source": "reddit",
                "source_label": f"r/{subreddit}" if subreddit else "Reddit",
                "title": title,
                "url": url,
                "snippet": (content or title)[:300],
                "score": 0,
                "comments": 0,
                "created_at": published or None,
                "author": author or None,
                "_post_id": post_id_match.group(1) if post_id_match else None,
                "_subreddit": subreddit,
            })

        return items

    async def _brave_reddit_items(
        self, query: str, tokens: Iterable[str]
    ) -> List[Dict[str, Any]]:
        """Fallback Reddit search through public web results.

        Used only when Reddit's own RSS search is unavailable or rate-limited.
        """
        html_text = await self._get_html(
            BRAVE_SEARCH_URL,
            {"q": f"site:reddit.com {query}", "source": "web"},
        )
        soup = BeautifulSoup(html_text, "html.parser")
        items: List[Dict[str, Any]] = []
        seen: set = set()

        for block in soup.select("div.result-content"):
            link = block.select_one("a[href]")
            if link is None:
                continue
            url = (link.get("href") or "").strip()
            if "reddit.com" not in url or "/comments/" not in url:
                continue
            if url in seen:
                continue

            title_el = block.select_one(".title")
            if title_el is None:
                continue
            title = (title_el.get("title") or title_el.get_text(" ", strip=True)).strip()
            title = re.sub(
                r"^r/[^:]+ on Reddit:\s*", "", title, flags=re.IGNORECASE
            ).strip()

            snippet_el = block.select_one(".inline-qa-question p")
            snippet = ""
            if snippet_el is not None:
                snippet = " ".join(snippet_el.get_text(" ", strip=True).split())

            if not self._matches(f"{title} {snippet} {url}", tokens):
                continue

            subreddit_match = re.search(r"/r/([^/]+)/", url)
            subreddit = subreddit_match.group(1) if subreddit_match else ""
            post_id_match = re.search(r"/comments/([a-z0-9]+)", url, flags=re.IGNORECASE)

            items.append({
                "source": "reddit",
                "source_label": f"r/{subreddit}" if subreddit else "Reddit",
                "title": title or "Reddit discussion",
                "url": url,
                "snippet": (snippet or title)[:300],
                "score": 0,
                "comments": 0,
                "created_at": None,
                "author": None,
                "_post_id": post_id_match.group(1) if post_id_match else None,
                "_subreddit": subreddit,
            })
            seen.add(url)

        return items

    def _finalize_reddit_posts(
        self,
        posts: List[Dict[str, Any]],
        company_name: str,
        query: str,
        note: str,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        candidates = {
            candidate.lower()
            for candidate in self._subreddit_candidates(company_name, query)
        }
        detected_subreddit = next(
            (
                post.get("_subreddit")
                for post in posts
                if (post.get("_subreddit") or "").lower() in candidates
            ),
            None,
        )
        subreddit = None
        if detected_subreddit:
            subreddit = {
                "name": detected_subreddit,
                "title": f"r/{detected_subreddit}",
                "subscribers": None,
                "url": f"https://www.reddit.com/r/{detected_subreddit}/",
                "description": "Detected from Reddit search results",
            }

        unique_posts: Dict[str, Dict[str, Any]] = {}
        for post in posts:
            key = post.get("_post_id") or post["url"]
            unique_posts.setdefault(key, post)
        return list(unique_posts.values()), subreddit, note

    async def _reddit_items(
        self, company_name: str, query: str, tokens: Iterable[str]
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        # Reddit's public RSS search is the primary path because anonymous
        # JSON requests are commonly blocked.
        try:
            rss_posts = await self._reddit_rss_items(query, tokens)
            rss_ok = True
        except Exception as exc:
            logger.warning(
                "Reddit RSS search failed (%s); trying public web-search fallback",
                exc,
            )
            rss_posts = []
            rss_ok = False

        if rss_posts:
            return self._finalize_reddit_posts(
                rss_posts,
                company_name,
                query,
                "Reddit mentions via public RSS search",
            )

        try:
            web_posts = await self._brave_reddit_items(query, tokens)
        except Exception as exc:
            logger.warning("Reddit web-search fallback failed (%s)", exc)
            web_posts = []
        if web_posts:
            return self._finalize_reddit_posts(
                web_posts,
                company_name,
                query,
                "Reddit mentions via public web search",
            )
        if rss_ok:
            return [], None, "Reddit RSS search returned no matches"

        # Best-effort archive fallback for environments where both public
        # search paths are unavailable. PullPush may rate-limit.
        subreddit = await self._lookup_subreddit(company_name, query)
        posts: List[Dict[str, Any]] = []

        if not subreddit:
            for candidate in self._subreddit_candidates(company_name, query)[:2]:
                try:
                    candidate_posts = await self._pullpush_submissions(
                        {"subreddit": candidate},
                        tokens,
                        require_match=False,
                    )
                except Exception:
                    logger.debug(
                        "Could not check r/%s via public Reddit archive",
                        candidate,
                        exc_info=True,
                    )
                    continue
                if candidate_posts:
                    subreddit = {
                        "name": candidate,
                        "title": f"r/{candidate}",
                        "subscribers": None,
                        "url": f"https://www.reddit.com/r/{candidate}/",
                        "description": "Found via public Reddit archive",
                    }
                    posts.extend(candidate_posts)
                    break

        if subreddit and not posts:
            try:
                posts.extend(
                    await self._pullpush_submissions(
                        {"subreddit": subreddit["name"]},
                        tokens,
                        require_match=False,
                    )
                )
            except Exception:
                logger.warning(
                    "Could not load posts from r/%s", subreddit["name"], exc_info=True
                )

        posts.extend(
            await self._pullpush_submissions({"title": query}, tokens)
        )

        # Preserve one copy of each submission before fetching comments.
        unique_posts: Dict[str, Dict[str, Any]] = {}
        for post in posts:
            key = post.get("_post_id") or post["url"]
            if key not in unique_posts:
                unique_posts[key] = post
        ranked_posts = sorted(
            unique_posts.values(),
            key=lambda item: item["score"] + item["comments"] * 2,
            reverse=True,
        )

        comments: List[Dict[str, Any]] = []
        for post in ranked_posts[:3]:
            if post.get("comments", 0) <= 0:
                continue
            try:
                comments.extend(
                    await self._pullpush_comments(post.get("_post_id") or "")
                )
            except Exception:
                logger.warning(
                    "Could not load comments for Reddit post %s",
                    post.get("_post_id"),
                    exc_info=True,
                )

        items = ranked_posts + comments
        note = "Reddit mentions via PullPush archive" if not subreddit else None
        return items, subreddit, note

    async def _hacker_news_items(
        self, query: str, tokens: Iterable[str]
    ) -> List[Dict[str, Any]]:
        payload = await self._get_json(
            HACKER_NEWS_API_URL,
            {"query": query, "tags": "story", "hitsPerPage": 20},
        )
        items: List[Dict[str, Any]] = []
        for hit in payload.get("hits") or []:
            title = (hit.get("title") or "").strip()
            story_text = _strip_html(hit.get("story_text") or "")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not title or not self._matches(f"{title} {url} {story_text}", tokens):
                continue
            items.append({
                "source": "hackernews",
                "source_label": "Hacker News",
                "title": title,
                "url": url,
                "snippet": (story_text or title)[:300],
                "score": int(hit.get("points") or 0),
                "comments": int(hit.get("num_comments") or 0),
                "created_at": hit.get("created_at"),
                "author": hit.get("author"),
            })
        return items

    async def _news_items(
        self, query: str, tokens: Iterable[str]
    ) -> List[Dict[str, Any]]:
        rss = await self._get_text(
            BING_NEWS_RSS_URL,
            {"q": query, "format": "rss"},
        )
        root = ET.fromstring(rss)
        items: List[Dict[str, Any]] = []
        for entry in root.findall("./channel/item")[:25]:
            title = _strip_html(entry.findtext("title") or "")
            description = _strip_html(entry.findtext("description") or "")
            link = (entry.findtext("link") or "").strip()
            if not title or not link or not self._matches(f"{title} {description}", tokens):
                continue
            items.append({
                "source": "news",
                "source_label": entry.findtext("source") or "News",
                "title": title,
                "url": link,
                "snippet": (description or title)[:300],
                "score": 0,
                "comments": 0,
                "created_at": _iso_from_rss_date(entry.findtext("pubDate") or ""),
                "author": None,
            })
        return items

    def _dedupe(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        result = []
        for item in items:
            key = item.get("url") or item.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    async def _collect(
        self, company_name: str, domain: str
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[Dict[str, Any]], str, str]:
        terms = self._company_terms(company_name, domain)
        query = terms["query"]
        tokens = terms["tokens"]

        results = await asyncio.gather(
            self._reddit_items(company_name, query, tokens),
            self._hacker_news_items(terms["name_query"], tokens),
            self._news_items(terms["name_query"], tokens),
            return_exceptions=True,
        )

        source_results = [
            ("Reddit", results[0]),
            ("Hacker News", results[1]),
            ("News", results[2]),
        ]
        items: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        subreddit = None
        reddit_note = None

        for name, result in source_results:
            if isinstance(result, Exception):
                logger.warning("Public opinion source %s failed", name, exc_info=result)
                sources.append({"name": name, "status": "error", "count": 0})
                continue

            if name == "Reddit":
                source_items, subreddit, reddit_note = result
            else:
                source_items = result

            source_items = [
                {key: value for key, value in item.items() if not key.startswith("_")}
                for item in source_items
            ]
            items.extend(source_items)
            sources.append({
                "name": name,
                "status": "ok" if source_items else "empty",
                "count": len(source_items),
            })

        items = self._dedupe(items)
        items.sort(
            key=lambda item: item.get("score", 0) + item.get("comments", 0) * 2,
            reverse=True,
        )
        items = items[: self.max_items]

        return items, subreddit, sources, terms["display_name"], query

    async def check(
        self,
        company_id: int,
        company_name: str,
        domain: str,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        cache_key = f"{company_id}:{(domain or company_name).lower()}"
        if not refresh and cache_key in self.cache:
            cached = dict(self.cache[cache_key])
            cached["cached"] = True
            return cached

        items, subreddit, sources, display_name, query = await self._collect(
            company_name, domain
        )
        sentiment = await llm_service.summarize_public_opinion(display_name, items)

        result = {
            "company": display_name,
            "query": query,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "subreddit": subreddit,
            "sources": sources,
            "sentiment": sentiment,
            "items": items,
            "disclaimer": (
                "Public opinion is collected automatically from Reddit, Hacker News, "
                "and news search. It may be incomplete or unrepresentative. Sentiment "
                "is an AI-generated summary based only on the linked mentions."
            ),
        }
        self.cache[cache_key] = result
        return result


public_opinion_service = PublicOpinionService()
