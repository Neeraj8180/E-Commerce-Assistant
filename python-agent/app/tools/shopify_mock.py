"""Client for the Shopify-compatible service."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.tools._instrument import tool
from app.validation import (
    MAX_REASON_CHARS,
    ValidationError,
    require_order_id,
    require_sku,
    sanitize_text,
    validate_item_skus,
)

_RETRY_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.HTTPStatusError)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.shopify_mock_url, timeout=10.0)


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.3, min=0.3, max=2),
        retry=retry_if_exception_type(_RETRY_ERRORS),
        reraise=True,
    ):
        with attempt:
            async with _client() as c:
                resp = await c.post(path, json=payload)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("shopify 5xx", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
    raise RuntimeError("unreachable")


def _clean_reason(reason: str) -> str:
    cleaned = sanitize_text(reason, max_chars=MAX_REASON_CHARS)
    if not cleaned:
        raise ValidationError("reason is required")
    return cleaned


@tool("shopify_create_return")
async def create_return(order_id: str, item_skus: list[str], reason: str) -> dict[str, Any]:
    payload = {
        "order_id": require_order_id(order_id),
        "item_skus": validate_item_skus(item_skus),
        "reason": _clean_reason(reason),
    }
    return await _post("/returns", payload)


@tool("shopify_create_exchange")
async def create_exchange(order_id: str, original_sku: str, new_sku: str, reason: str) -> dict[str, Any]:
    original = require_sku(original_sku)
    new = require_sku(new_sku)
    if original == new:
        raise ValidationError("original_sku and new_sku must differ")
    payload = {
        "order_id": require_order_id(order_id),
        "original_sku": original,
        "new_sku": new,
        "reason": _clean_reason(reason),
    }
    return await _post("/exchanges", payload)
