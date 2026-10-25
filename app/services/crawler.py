import asyncio
import logging
import time
from typing import Dict, List, Optional, Set
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urldefrag,
    urlunparse,
)
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from bs4 import BeautifulSoup
from tldextract import extract

from app.core.config import settings

logger = logging.getLogger(__name__)

# Query parameters that never change the page content.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref",
}


class PoliteCrawler:
    def __init__(self):
        self.visited: Set[str] = set()
        self.max_pages = settings.CRAWL_MAX_PAGES
        self.max_depth = settings.CRAWL_MAX_DEPTH
        self.delay = settings.CRAWL_DELAY
        self.user_agent = settings.CRAWL_USER_AGENT
        self.timeout = settings.CRAWL_TIMEOUT
        self._robots: Dict[str, Optional[RobotFileParser]] = {}

    def is_same_domain(self, url: str, base_domain: str) -> bool:
        try:
            extracted = extract(url)
            url_domain = f"{extracted.domain}.{extracted.suffix}" if extracted.suffix else extracted.domain
            return url_domain == base_domain
        except Exception:
            logger.debug("Could not parse domain for %s", url, exc_info=True)
            return False

    def get_base_domain(self, url: str) -> str:
        try:
            extracted = extract(url)
            return f"{extracted.domain}.{extracted.suffix}" if extracted.suffix else extracted.domain
        except Exception:
            logger.debug("Could not parse base domain for %s", url, exc_info=True)
            parsed = urlparse(url)
            return parsed.netloc

    async def _load_robots(self, origin: str) -> Optional[RobotFileParser]:
        """Fetch and cache robots.txt once per origin."""
        if not settings.RESPECT_ROBOTS_TXT:
            return None

        if origin in self._robots:
            return self._robots[origin]

        robots_url = f"{origin}/robots.txt"
        parser: Optional[RobotFileParser] = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    robots_url, timeout=5, headers={"User-Agent": self.user_agent}
                )
            if response.status_code == 200:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                logger.debug("Loaded robots.txt from %s (%d bytes)", robots_url, len(response.text))
            else:
                logger.debug("No usable robots.txt at %s (HTTP %s); allowing crawl", robots_url, response.status_code)
        except Exception as exc:
            logger.warning("Could not read robots.txt at %s (%s); allowing crawl", robots_url, exc)

        self._robots[origin] = parser
        return parser

    async def can_fetch(self, url: str) -> bool:
        if not settings.RESPECT_ROBOTS_TXT:
            return True

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = await self._load_robots(origin)
        if parser is None:
            return True

        allowed = parser.can_fetch(self.user_agent, url)
        if not allowed:
            logger.debug("Blocked by robots.txt: %s", url)
        return allowed

    def normalize_url(self, url: str) -> str:
        """Canonicalize a URL: drop fragments/tracking params, normalize host/path."""
        try:
            url, _ = urldefrag(url)
            parsed = urlparse(url)
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc.lower()

            if scheme == "http" and netloc.endswith(":80"):
                netloc = netloc[:-3]
            elif scheme == "https" and netloc.endswith(":443"):
                netloc = netloc[:-4]

            path = parsed.path or "/"
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")

            query_pairs = [
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if key.lower() not in TRACKING_PARAMS
            ]
            query = urlencode(sorted(query_pairs))

            return urlunparse((scheme, netloc, path, "", query, ""))
        except Exception:
            logger.debug("Could not normalize URL %s", url, exc_info=True)
            return url

    def _extract_text(self, html: str) -> str:
        try:
            extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        except Exception:
            logger.warning("trafilatura failed; falling back to BeautifulSoup", exc_info=True)
            extracted = None

        if extracted and len(extracted.strip()) >= 50:
            return extracted

        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            logger.warning("BeautifulSoup extraction failed", exc_info=True)
            return ""

    async def crawl(self, start_url: str) -> List[dict]:
        base_domain = self.get_base_domain(start_url)
        results: List[dict] = []
        to_visit = [(start_url, 0)]  # (url, depth)
        self.visited = set()
        self._robots = {}

        stats = {
            "fetched": 0,
            "empty": 0,
            "non_html": 0,
            "http_error": 0,
            "robots_blocked": 0,
            "request_errors": 0,
        }
        started = time.monotonic()

        logger.info(
            "Crawl started for %s (domain=%s, max_pages=%d, max_depth=%d, delay=%.1fs)",
            start_url, base_domain, self.max_pages, self.max_depth, self.delay,
        )

        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=5),
            ) as client:
                while to_visit and len(results) < self.max_pages:
                    current_url, depth = to_visit.pop(0)
                    current_url = self.normalize_url(current_url)

                    if current_url in self.visited:
                        continue
                    if depth > self.max_depth:
                        logger.debug("Skipping %s: depth %d > max %d", current_url, depth, self.max_depth)
                        continue
                    if not self.is_same_domain(current_url, base_domain):
                        logger.debug("Skipping %s: outside domain %s", current_url, base_domain)
                        continue
                    if not await self.can_fetch(current_url):
                        stats["robots_blocked"] += 1
                        self.visited.add(current_url)
                        continue

                    self.visited.add(current_url)

                    try:
                        await asyncio.sleep(self.delay)
                        logger.debug("Fetching %s (depth=%d)", current_url, depth)
                        response = await client.get(current_url)

                        if response.status_code != 200:
                            stats["http_error"] += 1
                            logger.info(
                                "Skipping %s: HTTP %s", current_url, response.status_code
                            )
                            continue

                        content_type = response.headers.get("content-type", "")
                        if "text/html" not in content_type:
                            stats["non_html"] += 1
                            logger.debug(
                                "Skipping %s: non-HTML content-type %r", current_url, content_type
                            )
                            continue

                        stats["fetched"] += 1
                        html = response.text
                        extracted = self._extract_text(html)
                        text_len = len(extracted.strip()) if extracted else 0

                        links_found = 0
                        if depth < self.max_depth:
                            try:
                                soup = BeautifulSoup(html, "lxml")
                                for link in soup.find_all("a", href=True):
                                    href = link["href"]
                                    next_url = self.normalize_url(urljoin(current_url, href))
                                    parsed_next = urlparse(next_url)
                                    if parsed_next.scheme not in ("http", "https"):
                                        continue
                                    if (
                                        next_url not in self.visited
                                        and self.is_same_domain(next_url, base_domain)
                                    ):
                                        to_visit.append((next_url, depth + 1))
                                        links_found += 1
                            except Exception:
                                logger.warning("Failed to parse links on %s", current_url, exc_info=True)

                        if text_len:
                            results.append({
                                "url": current_url,
                                "html": html,
                                "text": extracted,
                                "status_code": response.status_code,
                            })
                        else:
                            stats["empty"] += 1

                        logger.info(
                            "Crawled %d/%d %s -> HTTP %s, %d bytes, %d chars, %d new links",
                            len(results), self.max_pages, current_url,
                            response.status_code, len(html), text_len, links_found,
                        )
                    except Exception:
                        stats["request_errors"] += 1
                        logger.warning("Error crawling %s (depth=%d)", current_url, depth, exc_info=True)
                        continue
        except Exception:
            logger.exception("Crawler failed while initializing or running for %s", start_url)
            raise

        elapsed = time.monotonic() - started
        logger.info(
            "Crawl finished for %s: %d pages in %.1fs (fetched=%d, empty=%d, non_html=%d, "
            "http_error=%d, robots_blocked=%d, request_errors=%d)",
            start_url, len(results), elapsed, stats["fetched"], stats["empty"],
            stats["non_html"], stats["http_error"], stats["robots_blocked"],
            stats["request_errors"],
        )
        return results
