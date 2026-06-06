"""Ollama provider implementation using the local HTTP API."""

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

log = logging.getLogger(__name__)


class OllamaProvider:
    """Ollama HTTP client.

    Targets the Ollama REST API: ``/api/generate`` for completions and
    ``/api/embeddings`` for vector embeddings. Retries transient failures
    with exponential backoff.
    """

    name = "ollama"

    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model
        self.timeout = settings.ollama_timeout_seconds
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if json_mode:
            payload["format"] = "json"

        data = await self._post_json("/api/generate", payload)
        return LLMResponse(
            text=data.get("response", "").strip(),
            model=self.model,
            prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
            completion_tokens=int(data.get("eval_count", 0) or 0),
            raw=data,
        )

    async def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("embed requires a non-empty string")
        payload = {"model": self.embed_model, "prompt": text}
        data = await self._post_json("/api/embeddings", payload)
        emb = data.get("embedding", [])
        if not isinstance(emb, list) or not emb:
            raise RuntimeError(f"Ollama returned unexpected embedding payload: {type(emb).__name__}")
        try:
            return [float(x) for x in emb]
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Ollama embedding contains non-numeric values") from exc

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
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("ollama 5xx", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError("unreachable")
