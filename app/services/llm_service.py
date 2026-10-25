import asyncio
import json
import logging
import re
from typing import Dict, List, Optional

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

POSITIVE_OPINION_WORDS = {
    "amazing", "awesome", "excellent", "fair", "good", "great", "helpful",
    "legit", "love", "positive", "recommend", "reliable", "solid", "transparent",
    "trustworthy", "valuable", "worth", "worthwhile",
}

NEGATIVE_OPINION_WORDS = {
    "avoid", "bad", "complaint", "disappointing", "fake", "issue", "misleading",
    "negative", "poor", "problem", "red flag", "scam", "spam", "suspicious",
    "terrible", "unethical", "unpaid", "waste", "worthless",
}


class EmptyResponseError(RuntimeError):
    """Raised when a model returns no usable answer (e.g. reasoning-only output)."""


def parse_json_object(text: str) -> Dict:
    """Extract the first JSON object from a model response."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("Model response did not contain a valid JSON object")


class LLMService:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        if self.provider == "openrouter":
            self.api_key = settings.OPENROUTER_API_KEY
            self.base_url = settings.OPENROUTER_BASE_URL
            self.model = settings.OPENROUTER_MODEL
            self.timeout = settings.OPENROUTER_TIMEOUT
            self.max_tokens = getattr(settings, "OPENROUTER_MAX_TOKENS", 1200)
            self.fallback_models = [
                m.strip()
                for m in (getattr(settings, "OPENROUTER_FALLBACK_MODELS", "") or "").split(",")
                if m.strip() and m.strip() != self.model
            ]
        elif self.provider == "openai":
            self.api_key = settings.OPENAI_API_KEY
            self.base_url = settings.OPENAI_BASE_URL
            self.model = settings.OPENAI_MODEL
            self.timeout = settings.OPENAI_TIMEOUT
            self.max_tokens = getattr(settings, "OPENAI_MAX_TOKENS", 1200)
            self.fallback_models = []
        elif self.provider == "anthropic":
            self.api_key = settings.ANTHROPIC_API_KEY
            self.base_url = settings.ANTHROPIC_BASE_URL
            self.model = settings.ANTHROPIC_MODEL
            self.timeout = settings.ANTHROPIC_TIMEOUT
            self.max_tokens = getattr(settings, "ANTHROPIC_MAX_TOKENS", 1200)
            self.fallback_models = []
        else:
            self.base_url = settings.OLLAMA_BASE_URL
            self.model = settings.OLLAMA_MODEL
            self.timeout = settings.OLLAMA_TIMEOUT
            self.fallback_models = []

    async def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        retry_delays: Optional[List[float]] = None,
    ) -> Dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Company Portal RAG Chatbot",
            "Content-Type": "application/json",
        }
        json_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
        }

        delays = retry_delays if retry_delays is not None else [1.0, 2.0, 4.0, 8.0]
        for attempt in range(1 + len(delays)):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=json_payload,
                    )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        sleep_s = float(retry_after) if retry_after else delays[attempt]
                    except Exception:
                        sleep_s = delays[attempt] if attempt < len(delays) else 10.0
                    if attempt < len(delays):
                        logger.warning(
                            "OpenRouter rate-limited (429); retrying in %.1fs (attempt %d/%d) model=%s",
                            sleep_s, attempt + 1, 1 + len(delays), model,
                        )
                        await asyncio.sleep(min(sleep_s, 30.0))
                        continue
                    raise httpx.HTTPStatusError("429 Too Many Requests", request=response.request, response=response)
                if response.status_code >= 500:
                    if attempt < len(delays):
                        logger.warning(
                            "OpenRouter error %s; retrying in %.1fs (attempt %d/%d) model=%s",
                            response.status_code, delays[attempt], attempt + 1, 1 + len(delays), model,
                        )
                        await asyncio.sleep(delays[attempt])
                        continue
                    response.raise_for_status()
                response.raise_for_status()
                data = response.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                answer = message.get("content")
                if isinstance(answer, list):
                    answer = "".join(
                        part.get("text", "")
                        for part in answer
                        if isinstance(part, dict)
                    )
                answer = (answer or "").strip()
                finish_reason = choice.get("finish_reason")
                reasoning = message.get("reasoning") or ""

                if not answer:
                    logger.warning(
                        "OpenRouter model %s returned empty content "
                        "(finish_reason=%s, reasoning_chars=%d, max_tokens=%d)",
                        model,
                        finish_reason,
                        len(reasoning) if isinstance(reasoning, str) else 0,
                        self.max_tokens,
                    )
                    raise EmptyResponseError(
                        f"Empty response from {model} (finish_reason={finish_reason})"
                    )

                usage = data.get("usage", {}) or {}
                total_tokens = usage.get("total_tokens", 0) or 0
                prompt_tokens = usage.get("prompt_tokens", 0) or 0
                completion_tokens = usage.get("completion_tokens", 0) or 0
                return {
                    "answer": answer,
                    "model": model,
                    "tokens": total_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_usd": "0.0000",
                }
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < len(delays):
                    retry_after = exc.response.headers.get("Retry-After")
                    try:
                        sleep_s = float(retry_after) if retry_after else delays[attempt]
                    except Exception:
                        sleep_s = delays[attempt] if attempt < len(delays) else 10.0
                    logger.warning(
                        "OpenRouter rate-limited (429); retrying in %.1fs (attempt %d/%d) model=%s",
                        sleep_s, attempt + 1, 1 + len(delays), model,
                    )
                    await asyncio.sleep(min(sleep_s, 30.0))
                    continue
                raise
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < len(delays):
                    logger.warning(
                        "OpenRouter network error; retrying in %.1fs (attempt %d/%d) model=%s",
                        delays[attempt], attempt + 1, 1 + len(delays), model, exc_info=True,
                    )
                    await asyncio.sleep(delays[attempt])
                    continue
                raise

        raise RuntimeError(f"OpenRouter request failed after retries for {model}")

    async def _call_openai_compatible(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        provider_name: str = "openai",
        extra_headers: Optional[Dict] = None,
    ) -> Dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        json_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
        }

        delays = [1.0, 2.0, 4.0]
        for attempt in range(1 + len(delays)):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=json_payload,
                    )
                if response.status_code >= 500 and attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                response.raise_for_status()
                data = response.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                answer = message.get("content")
                if isinstance(answer, list):
                    answer = "".join(part.get("text", "") for part in answer if isinstance(part, dict))
                answer = (answer or "").strip()
                if not answer:
                    raise EmptyResponseError(f"Empty response from {provider_name} model {model}")
                usage = data.get("usage", {}) or {}
                return {
                    "answer": answer,
                    "model": model,
                    "tokens": usage.get("total_tokens", 0) or 0,
                    "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
                    "completion_tokens": usage.get("completion_tokens", 0) or 0,
                    "cost_usd": "0.0000",
                }
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 and attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise
        raise RuntimeError(f"{provider_name} request failed after retries for {model}")

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> Dict:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-13",
            "Content-Type": "application/json",
        }
        json_payload = {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
        }
        delays = [1.0, 2.0, 4.0]
        for attempt in range(1 + len(delays)):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/messages",
                        headers=headers,
                        json=json_payload,
                    )
                if response.status_code >= 500 and attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                response.raise_for_status()
                data = response.json()
                content = data.get("content") or []
                answer_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        answer_parts.append(part.get("text", ""))
                answer = "".join(answer_parts).strip()
                if not answer:
                    raise EmptyResponseError(f"Empty response from anthropic model {model}")
                usage = data.get("usage", {}) or {}
                prompt_tokens = usage.get("input_tokens", 0) or 0
                completion_tokens = usage.get("output_tokens", 0) or 0
                return {
                    "answer": answer,
                    "model": model,
                    "tokens": prompt_tokens + completion_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_usd": "0.0000",
                }
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 and attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise
        raise RuntimeError(f"anthropic request failed after retries for {model}")

    async def _generate_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        retry_delays: Optional[List[float]] = None,
        models: Optional[List[str]] = None,
    ) -> Dict:
        models_to_try = models or ([self.model] + self.fallback_models)
        last_exc = None
        for idx, model in enumerate(models_to_try):
            try:
                logger.info("Trying OpenRouter model %s (%d/%d)", model, idx + 1, len(models_to_try))
                result = await self._call_openrouter(
                    system_prompt, user_prompt, model, retry_delays=retry_delays
                )
                if model != self.model:
                    logger.info("Succeeded with fallback OpenRouter model %s", model)
                return result
            except EmptyResponseError as exc:
                last_exc = exc
                if idx < len(models_to_try) - 1:
                    logger.warning(
                        "OpenRouter model %s returned no usable answer; trying fallback model",
                        model,
                    )
                    continue
                raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code != 401 and idx < len(models_to_try) - 1:
                    logger.warning(
                        "OpenRouter %s failed for %s; trying fallback model",
                        exc.response.status_code,
                        model,
                    )
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if idx < len(models_to_try) - 1:
                    logger.warning("OpenRouter request failed for %s (%s); trying fallback model", model, exc)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("All OpenRouter models failed")

    async def _generate_ollama(self, system_prompt: str, user_prompt: str) -> Dict:
        delays = [1.0, 2.0, 4.0]
        for attempt in range(1 + len(delays)):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/api/generate",
                        json={
                            "model": self.model,
                            "prompt": f"{system_prompt}\n\n{user_prompt}",
                            "stream": False,
                            "options": {"temperature": 0.1},
                        },
                    )
                if response.status_code >= 500 and attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                response.raise_for_status()
                data = response.json()
                answer = data.get("response", "")
                prompt_eval_count = data.get("prompt_eval_count", 0) or 0
                eval_count = data.get("eval_count", 0) or 0
                total_tokens = prompt_eval_count + eval_count
                return {
                    "answer": answer,
                    "model": self.model,
                    "tokens": total_tokens,
                    "prompt_tokens": prompt_eval_count,
                    "completion_tokens": eval_count,
                    "cost_usd": "0.0000",
                }
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < len(delays):
                    logger.warning("Ollama network error; retrying in %.1fs (attempt %d/%d)", delays[attempt], attempt + 1, 1 + len(delays))
                    await asyncio.sleep(delays[attempt])
                    continue
                raise

        raise RuntimeError("Ollama request failed after retries")

    async def _generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        openrouter_retry_delays: Optional[List[float]] = None,
        openrouter_models: Optional[List[str]] = None,
    ) -> Dict:
        if self.provider == "openrouter":
            return await self._generate_openrouter(
                system_prompt,
                user_prompt,
                retry_delays=openrouter_retry_delays,
                models=openrouter_models,
            )
        elif self.provider == "openai":
            return await self._call_openai_compatible(
                system_prompt,
                user_prompt,
                self.model,
                provider_name="openai",
            )
        elif self.provider == "anthropic":
            return await self._call_anthropic(system_prompt, user_prompt, self.model)
        return await self._generate_ollama(system_prompt, user_prompt)

    @staticmethod
    def _heuristic_public_opinion(items: List[Dict], reason: Optional[str] = None) -> Dict:
        text = " ".join(
            f"{item.get('title', '')} {item.get('snippet', '')}" for item in items
        ).lower()

        positive_hits = sorted({word for word in POSITIVE_OPINION_WORDS if word in text})
        negative_hits = sorted({word for word in NEGATIVE_OPINION_WORDS if word in text})

        if positive_hits and negative_hits:
            label = "mixed"
        elif positive_hits:
            label = "positive"
        elif negative_hits:
            label = "negative"
        else:
            label = "neutral"

        source_labels = sorted({
            item.get("source_label", item.get("source", "web")) for item in items
        })
        reason = reason or "the AI summarizer was unavailable"
        summary = (
            f"Found {len(items)} public mention(s) across "
            f"{', '.join(source_labels)}. Keyword signals lean {label}. "
            "Review the linked posts for context; this is a keyword-based fallback "
            f"because {reason}."
        )

        return {
            "label": label,
            "summary": summary,
            "positives": positive_hits[:4],
            "negatives": negative_hits[:4],
            "themes": [],
            "method": "heuristic",
        }

    async def summarize_public_opinion(self, company_name: str, items: List[Dict]) -> Dict:
        """Summarize public mentions into a short sentiment report."""
        if not items:
            return {
                "label": "unknown",
                "summary": "No public discussions were found for this company.",
                "positives": [],
                "negatives": [],
                "themes": [],
                "method": "none",
            }

        excerpt_lines = []
        for idx, item in enumerate(items[:10], start=1):
            excerpt_lines.append(
                f"{idx}. [{item.get('source_label', item.get('source', 'web'))}] "
                f"{item.get('title', '')}\n"
                f"   {item.get('snippet', '')[:350]}\n"
                f"   score={item.get('score', 0)} comments={item.get('comments', 0)}"
            )
        excerpts = "\n".join(excerpt_lines)

        system_prompt = """You are a careful public-opinion analyst. You will receive public web mentions about a company. Summarize only what the mentions say. Do not add facts that are not in the mentions.

Return ONLY a valid JSON object with this exact shape:
{
  "sentiment": "positive" | "mixed" | "negative" | "neutral" | "unknown",
  "summary": "2-4 sentence summary of the public discussion",
  "positives": ["short positive point", "..."],
  "negatives": ["short negative point", "..."],
  "themes": ["short theme", "..."]
}

Rules:
- Use "unknown" if there is not enough information.
- Some mentions may be written by the company itself. Distinguish official company statements from independent public opinion when relevant.
- Keep each list item short.
- Do not include markdown, code fences, or any text outside the JSON object."""

        user_prompt = f"""Company: {company_name}

Public mentions:
{excerpts}

Summarize the public opinion now."""

        openrouter_models = None
        preferred_models = [
            model.strip()
            for model in (settings.PUBLIC_OPINION_LLM_MODELS or "").split(",")
            if model.strip()
        ]
        if self.provider == "openrouter" and preferred_models:
            openrouter_models = []
            for model in [*preferred_models, self.model, *self.fallback_models]:
                if model and model not in openrouter_models:
                    openrouter_models.append(model)

        try:
            result = await self._generate_text(
                system_prompt,
                user_prompt,
                openrouter_retry_delays=[0.5],
                openrouter_models=openrouter_models,
            )
            parsed = parse_json_object(result.get("answer", ""))

            allowed_labels = {"positive", "mixed", "negative", "neutral", "unknown"}
            label = str(parsed.get("sentiment") or parsed.get("label") or "unknown").lower().strip()
            if label not in allowed_labels:
                label = "unknown"

            def clean_list(value) -> List[str]:
                if not isinstance(value, list):
                    return []
                return [str(item)[:200] for item in value if str(item).strip()][:5]

            summary = str(parsed.get("summary") or "").strip()
            if not summary:
                raise ValueError("Public opinion summary was empty")

            return {
                "label": label,
                "summary": summary,
                "positives": clean_list(parsed.get("positives")),
                "negatives": clean_list(parsed.get("negatives")),
                "themes": clean_list(parsed.get("themes")),
                "method": "llm",
            }
        except Exception as exc:
            logger.warning(
                "Could not generate LLM public-opinion summary (%s); using heuristic fallback",
                exc,
            )
            reason = None
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                reason = (
                    "the free AI models are temporarily rate-limited (HTTP 429); "
                    "refresh later for an AI-generated summary"
                )
            return self._heuristic_public_opinion(items, reason=reason)

    async def generate_answer(self, question: str, context_chunks: List[Dict]) -> Dict:
        # Build context
        context = "\n\n".join([f"[Source: {c['url']}]\n{c['text']}" for c in context_chunks])

        system_prompt = """You are a helpful assistant that answers questions about a specific company based ONLY on the provided context.

Rules:
- Answer ONLY using information from the provided context. Do not use prior knowledge.
- If the answer is not found in the context, say "I don't know based on the available information."
- Always cite your sources by mentioning the URLs when relevant.
- Be concise and accurate.
- Do not make up information."""

        user_prompt = f"""Context:
{context}

Question: {question}

Answer:"""

        try:
            return await self._generate_text(system_prompt, user_prompt)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                return {
                    "answer": (
                        "The AI model is temporarily rate-limited (HTTP 429). "
                        "All configured OpenRouter free models were tried. Please wait a moment and try again, "
                        "or switch to a local Ollama model in your .env (LLM_PROVIDER=ollama)."
                    ),
                    "model": self.model,
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": "0.0000",
                }
            return {
                "answer": f"Error generating answer: {exc.response.status_code} {exc.response.reason_phrase}",
                "model": self.model,
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": "0.0000",
            }
        except Exception as exc:
            logger.exception("Failed to generate answer")
            return {
                "answer": f"Error generating answer: {str(exc)}",
                "model": self.model,
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": "0.0000",
            }


llm_service = LLMService()
