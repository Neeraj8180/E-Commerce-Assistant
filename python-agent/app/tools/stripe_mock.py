"""Client for the Stripe-compatible refund service."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.tools._instrument import tool
from app.validation import (
    ValidationError,
    is_idempotency_key,
    require_order_id,
    require_refund_amount,
)

_RETRY_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.HTTPStatusError)


@tool("stripe_process_refund")
async def process_refund(order_id: str, amount: float, idempotency_key: str) -> dict[str, Any]:
    if not is_idempotency_key(idempotency_key):
        raise ValidationError("idempotency_key must match [A-Za-z0-9_-]{8,128}")
    payload = {
        "order_id": require_order_id(order_id),
        "amount": require_refund_amount(amount),
        "idempotency_key": idempotency_key,
    }
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.3, min=0.3, max=2),
        retry=retry_if_exception_type(_RETRY_ERRORS),
        reraise=True,
    ):
        with attempt:
            async with httpx.AsyncClient(base_url=settings.stripe_mock_url, timeout=10.0) as c:
                resp = await c.post("/refunds", json=payload)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("stripe 5xx", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
    raise RuntimeError("unreachable")
