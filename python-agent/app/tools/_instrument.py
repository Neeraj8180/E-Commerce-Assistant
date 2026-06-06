"""Tool-call instrumentation helpers (metrics + tracing)."""

from __future__ import annotations

import functools
import time
from typing import Any, Awaitable, Callable, TypeVar

from app.observability import TOOL_CALL_LATENCY, TOOL_CALL_TOTAL, get_logger
from app.observability.tracing import tracer

log = get_logger(__name__)
T = TypeVar("T")


def tool(name: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that adds metrics, logging, and an OTel span around a tool call."""

    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.perf_counter()
            with tracer().start_as_current_span(f"tool.{name}") as span:
                try:
                    result = await fn(*args, **kwargs)
                    TOOL_CALL_TOTAL.labels(tool_name=name, status="success").inc()
                    return result
                except Exception as exc:
                    TOOL_CALL_TOTAL.labels(tool_name=name, status="error").inc()
                    span.record_exception(exc)
                    log.error("tool_failed", tool=name, error=str(exc))
                    raise
                finally:
                    TOOL_CALL_LATENCY.labels(tool_name=name).observe(time.perf_counter() - start)

        return wrapper

    return deco
