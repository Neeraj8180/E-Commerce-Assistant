"""Stripe-compatible refund service.

Real, Postgres-backed implementation of the subset of the Stripe API used
by the agent system. State is persistent; idempotency keys behave exactly
like Stripe's: re-sending the same key returns the original response, and
a mismatched payload under an existing key returns HTTP 409.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

DATABASE_URL = os.environ["DATABASE_URL"]
AUTO_APPROVE_LIMIT = float(os.getenv("REFUND_AUTO_APPROVE_LIMIT", "50.0"))
SERVICE_NAME = "stripe-mock"

ORDER_ID_RE = re.compile(r"^ORD-[0-9]{3,12}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")
REFUND_ID_RE = re.compile(r"^REF-[A-Z0-9-]{1,32}$")
MAX_REFUND_AMOUNT = 100_000.0

_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=8, command_timeout=10)
    try:
        yield
    finally:
        if _pool is not None:
            await _pool.close()
            _pool = None


app = FastAPI(title="Stripe Service", version="1.0.0", lifespan=lifespan)


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not ready")
    return _pool


class RefundRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=32)
    amount: float = Field(..., gt=0, le=MAX_REFUND_AMOUNT)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

    @field_validator("order_id")
    @classmethod
    def _check_order(cls, v: str) -> str:
        if not ORDER_ID_RE.match(v):
            raise ValueError("invalid order_id format")
        return v

    @field_validator("idempotency_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        if not IDEMPOTENCY_KEY_RE.match(v):
            raise ValueError("idempotency_key must match [A-Za-z0-9_-]{8,128}")
        return v

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("amount must be a finite number")
        return round(v, 2)


@app.get("/health")
async def health() -> dict:
    try:
        async with pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "service": SERVICE_NAME, "dependencies": {"postgres": "up"}}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}") from exc


@app.post("/refunds")
async def process_refund(req: RefundRequest) -> dict:
    request_hash = _hash_request(req)

    async with pool().acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                """
                SELECT request_hash, response
                FROM mock_idempotency_keys
                WHERE key = $1 AND endpoint = $2
                FOR UPDATE
                """,
                req.idempotency_key, "POST /refunds",
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="idempotency key reused with a different request payload",
                    )
                resp = existing["response"]
                return json.loads(resp) if isinstance(resp, str) else dict(resp)

            order = await conn.fetchrow("SELECT id, total_amount FROM orders WHERE id = $1", req.order_id)
            if order is None:
                raise HTTPException(status_code=404, detail=f"order {req.order_id} not found")
            if req.amount > float(order["total_amount"]) + 0.01:
                raise HTTPException(
                    status_code=422,
                    detail=f"refund {req.amount} exceeds order total {order['total_amount']}",
                )

            refund_id = f"REF-{uuid.uuid4().hex[:10].upper()}"
            status = "succeeded" if req.amount < AUTO_APPROVE_LIMIT else "pending_review"

            await conn.execute(
                """
                INSERT INTO mock_refunds (refund_id, order_id, amount, currency, status)
                VALUES ($1, $2, $3, 'USD', $4)
                """,
                refund_id, req.order_id, req.amount, status,
            )

            response = {
                "refund_id": refund_id,
                "order_id": req.order_id,
                "amount": req.amount,
                "currency": "USD",
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            await conn.execute(
                """
                INSERT INTO mock_idempotency_keys (key, endpoint, request_hash, response)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                req.idempotency_key, "POST /refunds", request_hash, json.dumps(response),
            )
            return response


@app.get("/refunds/{refund_id}")
async def get_refund(refund_id: str) -> dict:
    if not REFUND_ID_RE.match(refund_id):
        raise HTTPException(status_code=422, detail="invalid refund_id format")
    async with pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM mock_refunds WHERE refund_id = $1", refund_id)
    if row is None:
        raise HTTPException(status_code=404, detail="refund not found")
    return {
        "refund_id": row["refund_id"],
        "order_id": row["order_id"],
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _hash_request(req: RefundRequest) -> str:
    payload = json.dumps({"order_id": req.order_id, "amount": round(req.amount, 2)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
