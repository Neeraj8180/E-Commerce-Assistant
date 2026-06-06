"""LLM provider abstraction.

The default provider is Ollama; alternative providers (OpenAI, vLLM, etc.)
can be added by implementing :class:`LLMProvider` and wiring them into
:func:`get_llm_provider`.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.base import LLMProvider, LLMResponse
from app.llm.ollama import OllamaProvider


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaProvider()
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


__all__ = ["LLMProvider", "LLMResponse", "get_llm_provider"]
