"""Groq provider: hosted Llama / Mixtral via OpenAI-compatible API.

Groq does not currently offer embeddings, so embed() delegates to the
configured Ollama provider. Chat completions go to Groq for production-grade
latency on `llama-3.3-70b-versatile` and similar models.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from app.config import settings
from app.llm.base import LLMResponse
from app.llm.ollama import OllamaProvider

log = logging.getLogger(__name__)


class GroqProvider:
    """Groq HTTP client using the OpenAI-compatible chat-completions endpoint."""

    name = "groq"

    def __init__(self) -> None:
        api_key = settings.groq_api_key or ""
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=groq requires GROQ_API_KEY to be set in the environment"
            )
        self.api_key = api_key
        self.base_url = settings.groq_base_url.rstrip("/")
        self.model = settings.groq_model
        self.timeout = settings.groq_timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._embedder = OllamaProvider()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        await self._embedder.aclose()

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "stream": False,
        }
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = await self._post_json("/chat/completions", payload)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return LLMResponse(
            text=(message.get("content") or "").strip(),
            model=data.get("model", self.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw=data,
        )

    async def embed(self, text: str) -> list[float]:
        return await self._embedder.embed(text)

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with explicit 429-aware backoff.

        Groq returns 429 with a `Retry-After` header (seconds) and/or
        `x-ratelimit-reset-*` hints when the per-minute request or token
        budget is exhausted. We honor `Retry-After` first, then fall back
        to exponential backoff with jitter. 5xx errors and transient
        network failures are retried the same way.
        """
        url = self.base_url + path
        max_attempts = 6
        transient = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)

        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._http().post(url, json=payload)
            except transient as exc:
                if attempt == max_attempts:
                    raise
                delay = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                log.warning("groq transient error (attempt %d/%d): %s; sleeping %.1fs",
                            attempt, max_attempts, exc, delay)
                await asyncio.sleep(delay)
                continue

            if resp.status_code < 400:
                return resp.json()

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == max_attempts:
                    raise httpx.HTTPStatusError(
                        f"groq {resp.status_code} after {max_attempts} attempts: {resp.text[:200]}",
                        request=resp.request,
                        response=resp,
                    )
                delay = self._compute_retry_delay(resp, attempt)
                log.warning("groq %d (attempt %d/%d); sleeping %.1fs",
                            resp.status_code, attempt, max_attempts, delay)
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError("unreachable")

    @staticmethod
    def _compute_retry_delay(resp: httpx.Response, attempt: int) -> float:
        """Honor Retry-After if present, else exponential backoff with jitter.

        Cap at 30 s so a misbehaving header can't stall the whole stack.
        """
        retry_after = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
        reset_hint = (
            resp.headers.get("x-ratelimit-reset-tokens")
            or resp.headers.get("x-ratelimit-reset-requests")
        )
        if reset_hint:
            try:
                return min(float(reset_hint.rstrip("s")), 30.0)
            except ValueError:
                pass
        return min(2 ** attempt, 30) + random.uniform(0, 0.5)
