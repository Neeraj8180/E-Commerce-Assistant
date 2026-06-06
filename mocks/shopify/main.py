"""Shopify-compatible service.

Implements the Returns and Exchanges subset of Shopify's Admin API against
a real Postgres database. State is persisted across restarts and inventory
is tracked per-SKU, so swapping the real Shopify base URL into the agent at
a later date is purely a config change.
"""

from __future__ import annotations

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
SERVICE_NAME = "shopify-mock"

ORDER_ID_RE = re.compile(r"^ORD-[0-9]{3,12}$")
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,63}$")
RMA_ID_RE = re.compile(r"^RMA-[A-Z0-9-]{1,32}$")
MAX_ITEMS = 50
MAX_REASON_CHARS = 500

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


app = FastAPI(title="Shopify Service", version="1.0.0", lifespan=lifespan)


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not ready")
    return _pool


class ReturnRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=32)
    item_skus: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    reason: str = Field(..., min_length=1, max_length=MAX_REASON_CHARS)

    @field_validator("order_id")
    @classmethod
    def _check_order(cls, v: str) -> str:
        if not ORDER_ID_RE.match(v):
            raise ValueError("invalid order_id format")
        return v

    @field_validator("item_skus")
    @classmethod
    def _check_skus(cls, v: list[str]) -> list[str]:
        for s in v:
            if not SKU_RE.match(s):
                raise ValueError(f"invalid sku: {s!r}")
        return v


class ExchangeRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=32)
    original_sku: str = Field(..., min_length=2, max_length=64)
    new_sku: str = Field(..., min_length=2, max_length=64)
    reason: str = Field(..., min_length=1, max_length=MAX_REASON_CHARS)

    @field_validator("order_id")
    @classmethod
    def _check_order(cls, v: str) -> str:
        if not ORDER_ID_RE.match(v):
            raise ValueError("invalid order_id format")
        return v

    @field_validator("original_sku", "new_sku")
    @classmethod
    def _check_sku(cls, v: str) -> str:
        if not SKU_RE.match(v):
            raise ValueError("invalid sku format")
        return v


@app.get("/health")
async def health() -> dict:
    try:
        async with pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "service": SERVICE_NAME, "dependencies": {"postgres": "up"}}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}") from exc


@app.post("/returns")
async def create_return(req: ReturnRequest) -> dict:
    async with pool().acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT id, status, items FROM orders WHERE id = $1 FOR UPDATE",
                req.order_id,
            )
            if order is None:
                raise HTTPException(status_code=404, detail=f"order {req.order_id} not found")
            if order["status"] != "delivered":
                raise HTTPException(
                    status_code=409,
                    detail=f"order status is '{order['status']}'; only delivered orders can be returned",
                )

            order_skus = {item["sku"] for item in _items(order)}
            requested = list(req.item_skus) or list(order_skus)
            unknown = [s for s in requested if s not in order_skus]
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail=f"items {unknown} are not part of order {req.order_id}",
                )

            rma_id = f"RMA-{uuid.uuid4().hex[:10].upper()}"
            label = f"https://shopify.local/labels/{rma_id}.pdf"
            await conn.execute(
                """
                INSERT INTO mock_returns (rma_id, order_id, item_skus, reason, status, shipping_label_url)
                VALUES ($1, $2, $3::jsonb, $4, 'created', $5)
                """,
                rma_id, req.order_id, json.dumps(requested), req.reason, label,
            )

            return {
                "rma_id": rma_id,
                "order_id": req.order_id,
                "items": requested,
                "reason": req.reason,
                "status": "created",
                "shipping_label_url": label,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }


@app.post("/exchanges")
async def create_exchange(req: ExchangeRequest) -> dict:
    if req.original_sku == req.new_sku:
        raise HTTPException(status_code=422, detail="original_sku and new_sku must differ")

    async with pool().acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT id, status, items FROM orders WHERE id = $1 FOR UPDATE",
                req.order_id,
            )
            if order is None:
                raise HTTPException(status_code=404, detail=f"order {req.order_id} not found")
            if order["status"] != "delivered":
                raise HTTPException(
                    status_code=409,
                    detail=f"order status is '{order['status']}'; only delivered orders can be exchanged",
                )
            order_skus = {item["sku"] for item in _items(order)}
            if req.original_sku not in order_skus:
                raise HTTPException(
                    status_code=422,
                    detail=f"original_sku {req.original_sku} is not part of order {req.order_id}",
                )

            stock = await conn.fetchrow(
                "SELECT sku, stock_quantity FROM inventory WHERE sku = $1 FOR UPDATE",
                req.new_sku,
            )
            if stock is None:
                raise HTTPException(status_code=404, detail=f"sku {req.new_sku} not in catalogue")

            if stock["stock_quantity"] <= 0:
                return {
                    "exchange_id": None,
                    "order_id": req.order_id,
                    "original_sku": req.original_sku,
                    "new_sku": req.new_sku,
                    "status": "out_of_stock",
                }

            await conn.execute(
                "UPDATE inventory SET stock_quantity = stock_quantity - 1, updated_at = NOW() WHERE sku = $1",
                req.new_sku,
            )

            exchange_id = f"EXC-{uuid.uuid4().hex[:10].upper()}"
            estimated_ship_at = datetime.now(timezone.utc)
            await conn.execute(
                """
                INSERT INTO mock_exchanges (exchange_id, order_id, original_sku, new_sku, reason,
                                            status, estimated_ship_at)
                VALUES ($1, $2, $3, $4, $5, 'created', $6)
                """,
                exchange_id, req.order_id, req.original_sku, req.new_sku, req.reason, estimated_ship_at,
            )

            return {
                "exchange_id": exchange_id,
                "order_id": req.order_id,
                "original_sku": req.original_sku,
                "new_sku": req.new_sku,
                "status": "created",
                "estimated_ship_at": estimated_ship_at.isoformat(),
            }


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> dict:
    if not ORDER_ID_RE.match(order_id):
        raise HTTPException(status_code=422, detail="invalid order_id format")
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, status, total_amount, currency, items, tracking_number, carrier,
                   placed_at, shipped_at, delivered_at, estimated_delivery
            FROM orders WHERE id = $1
            """,
            order_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")
    items = row["items"]
    if isinstance(items, str):
        items = json.loads(items)
    return {
        "id": row["id"],
        "status": row["status"],
        "total_amount": float(row["total_amount"]),
        "currency": row["currency"],
        "items": items,
        "tracking_number": row["tracking_number"],
        "carrier": row["carrier"],
        "placed_at": _iso(row["placed_at"]),
        "shipped_at": _iso(row["shipped_at"]),
        "delivered_at": _iso(row["delivered_at"]),
        "estimated_delivery": _iso(row["estimated_delivery"]),
    }


@app.get("/inventory/{sku}")
async def get_inventory(sku: str) -> dict:
    if not SKU_RE.match(sku):
        raise HTTPException(status_code=422, detail="invalid sku format")
    async with pool().acquire() as conn:
        row = await conn.fetchrow("SELECT sku, name, stock_quantity, unit_price FROM inventory WHERE sku = $1", sku)
    if row is None:
        raise HTTPException(status_code=404, detail=f"sku {sku} not found")
    return {
        "sku": row["sku"],
        "name": row["name"],
        "stock_quantity": int(row["stock_quantity"]),
        "unit_price": float(row["unit_price"]),
        "in_stock": int(row["stock_quantity"]) > 0,
    }


@app.get("/returns/{rma_id}")
async def get_return(rma_id: str) -> dict:
    if not RMA_ID_RE.match(rma_id):
        raise HTTPException(status_code=422, detail="invalid rma_id format")
    async with pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM mock_returns WHERE rma_id = $1", rma_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rma not found")
    item_skus = row["item_skus"]
    if isinstance(item_skus, str):
        item_skus = json.loads(item_skus)
    return {
        "rma_id": row["rma_id"],
        "order_id": row["order_id"],
        "item_skus": item_skus,
        "reason": row["reason"],
        "status": row["status"],
        "shipping_label_url": row["shipping_label_url"],
        "created_at": _iso(row["created_at"]),
    }


def _items(row) -> list[dict]:
    items = row["items"]
    return json.loads(items) if isinstance(items, str) else list(items)


def _iso(value) -> str | None:
    return value.isoformat() if value else None
