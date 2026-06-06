"""Order lookups: direct SQL against the canonical orders table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import get_pool
from app.tools._instrument import tool
from app.validation import ValidationError, is_order_id, require_order_id


def _row_to_order(row) -> dict[str, Any]:
    items = row["items"]
    if isinstance(items, str):
        items = json.loads(items)
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "status": row["status"],
        "total_amount": float(row["total_amount"]),
        "currency": row["currency"],
        "items": items,
        "tracking_number": row["tracking_number"],
        "carrier": row["carrier"],
        "placed_at": row["placed_at"].isoformat() if row["placed_at"] else None,
        "shipped_at": row["shipped_at"].isoformat() if row["shipped_at"] else None,
        "delivered_at": row["delivered_at"].isoformat() if row["delivered_at"] else None,
        "estimated_delivery": row["estimated_delivery"].isoformat() if row["estimated_delivery"] else None,
    }


@tool("get_order")
async def get_order(order_id: str) -> dict[str, Any] | None:
    order_id = require_order_id(order_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        return _row_to_order(row) if row else None


@tool("list_user_orders")
async def list_user_orders(user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(user_id, str) or not user_id:
        raise ValidationError("user_id is required")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValidationError("limit must be an integer between 1 and 50")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM orders WHERE user_id = $1 ORDER BY placed_at DESC LIMIT $2",
            user_id,
            limit,
        )
        return [_row_to_order(r) for r in rows]


def order_status_summary(order: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    status = order["status"]
    summary: dict[str, Any] = {"status": status, "delayed": False}

    if status == "delivered":
        summary["headline"] = "delivered"
        summary["delivered_at"] = order["delivered_at"]
    elif status == "shipped":
        eta = order.get("estimated_delivery")
        summary["headline"] = "in_transit"
        summary["tracking_number"] = order.get("tracking_number")
        summary["carrier"] = order.get("carrier")
        summary["estimated_delivery"] = eta
        if eta:
            eta_dt = datetime.fromisoformat(eta.replace("Z", "+00:00"))
            if eta_dt < now:
                summary["delayed"] = True
                summary["headline"] = "delayed"
    elif status == "pending":
        summary["headline"] = "processing"
    elif status == "cancelled":
        summary["headline"] = "cancelled"
    return summary


def is_within_return_window(order: dict[str, Any]) -> tuple[bool, str]:
    if not is_order_id(order.get("id", "")):
        return False, "order has an invalid id"
    if order["status"] != "delivered":
        return False, f"Order status is '{order['status']}'; only delivered orders can be returned."
    if not order.get("delivered_at"):
        return False, "Order has no delivery timestamp."
    delivered = datetime.fromisoformat(order["delivered_at"].replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - delivered).days
    if age_days > settings.return_window_days:
        return False, f"Delivered {age_days} days ago; outside the {settings.return_window_days}-day return window."
    return True, f"Delivered {age_days} days ago; within return window."
