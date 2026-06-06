"""Groq provider: hosted Llama / Mixtral via OpenAI-compatible API.

Groq does not currently offer embeddings, so embed() delegates to the
configured Ollama provider. Chat completions go to Groq for production-grade
latency on `llama-3.3-70b-versatile` and similar models.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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
        url = self.base_url + path
        retryable = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            retry=retry_if_exception_type(retryable),
            reraise=True,
        ):
            with attempt:
                resp = await self._http().post(url, json=payload)
                if resp.status_code == 429:
                    raise httpx.HTTPStatusError("groq rate limited", request=resp.request, response=resp)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("groq 5xx", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError("unreachable")
