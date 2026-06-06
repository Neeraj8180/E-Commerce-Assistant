"""Reusable validators and sanitisers used throughout the agent service.

Centralising these here means every layer (FastAPI schemas, tools, mocks,
orchestrator) enforces the same rules. Any change to the contract — e.g.
allowed order-id format — happens in one place.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

ORDER_ID_RE = re.compile(r"^ORD-[0-9]{3,12}$")
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,63}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")

MAX_MESSAGE_CHARS = 4000
MAX_REASON_CHARS = 500
MAX_REPLY_CHARS = 2000
MAX_CONTEXT_KEYS = 16
MAX_CONTEXT_KEY_CHARS = 64
MAX_CONTEXT_VALUE_CHARS = 1024
MAX_CONTEXT_LIST_ITEMS = 16

MAX_REFUND_AMOUNT = 100_000.0
MIN_REFUND_AMOUNT = 0.01

MAX_ITEM_SKUS = 50
MAX_MESSAGES_PER_CONVERSATION = 200


class ValidationError(ValueError):
    """Raised when input fails project-level validation."""


def is_order_id(value: str | None) -> bool:
    return bool(value) and bool(ORDER_ID_RE.match(value))


def is_sku(value: str | None) -> bool:
    return bool(value) and bool(SKU_RE.match(value))


def is_session_id(value: str | None) -> bool:
    return bool(value) and bool(SESSION_ID_RE.match(value))


def is_idempotency_key(value: str | None) -> bool:
    return bool(value) and bool(IDEMPOTENCY_KEY_RE.match(value))


def require_order_id(value: str) -> str:
    if not is_order_id(value):
        raise ValidationError(f"invalid order_id: {value!r}")
    return value


def require_sku(value: str) -> str:
    if not is_sku(value):
        raise ValidationError(f"invalid sku: {value!r}")
    return value


def require_refund_amount(amount: float | int) -> float:
    try:
        value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"refund amount is not numeric: {amount!r}") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise ValidationError("refund amount is NaN or infinite")
    if value < MIN_REFUND_AMOUNT:
        raise ValidationError(f"refund amount must be >= {MIN_REFUND_AMOUNT}")
    if value > MAX_REFUND_AMOUNT:
        raise ValidationError(f"refund amount exceeds maximum {MAX_REFUND_AMOUNT}")
    return round(value, 2)


def sanitize_text(value: str, *, max_chars: int) -> str:
    """Normalise unicode, strip control characters (except tab/newline/CR), and
    enforce a length cap. Used on every free-text input/output to prevent log
    injection, prompt-escape characters, and oversize payloads.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("text value must be a string")
    normalised = unicodedata.normalize("NFC", value)
    cleaned_chars: list[str] = []
    for ch in normalised:
        if ch in ("\t", "\n", "\r"):
            cleaned_chars.append(ch)
            continue
        if unicodedata.category(ch).startswith("C"):
            continue
        cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "…"
    return cleaned


def validate_item_skus(items: list[str] | None) -> list[str]:
    if not items:
        return []
    if not isinstance(items, list):
        raise ValidationError("item_skus must be a list")
    if len(items) > MAX_ITEM_SKUS:
        raise ValidationError(f"item_skus has {len(items)} entries; max {MAX_ITEM_SKUS}")
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            raise ValidationError("item_skus must contain only strings")
        sku = item.strip().upper()
        if not is_sku(sku):
            raise ValidationError(f"invalid sku in item_skus: {item!r}")
        if sku not in seen:
            out.append(sku)
            seen.add(sku)
    return out


CONTEXT_KEY_RE = re.compile(r"^[a-z0-9_]{1,%d}$" % MAX_CONTEXT_KEY_CHARS)


def validate_context(ctx: dict[str, Any] | None) -> dict[str, Any]:
    """Bound-checked, type-restricted copy of an arbitrary context map.

    Keys must match ``[a-z0-9_]`` (same rule the Go gateway enforces) so that
    a payload accepted upstream is accepted here, and vice-versa.
    """
    if ctx is None:
        return {}
    if not isinstance(ctx, dict):
        raise ValidationError("context must be an object")
    if len(ctx) > MAX_CONTEXT_KEYS:
        raise ValidationError(f"context has {len(ctx)} keys; max {MAX_CONTEXT_KEYS}")
    cleaned: dict[str, Any] = {}
    for raw_key, raw_val in ctx.items():
        if not isinstance(raw_key, str) or not CONTEXT_KEY_RE.match(raw_key):
            raise ValidationError(
                f"context key {raw_key!r} is invalid (use [a-z0-9_], 1..{MAX_CONTEXT_KEY_CHARS} chars)"
            )
        cleaned[raw_key] = _coerce_context_value(raw_key, raw_val)
    return cleaned


def _coerce_context_value(key: str, value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValidationError(f"context.{key} is NaN or infinite")
        return value
    if isinstance(value, str):
        return sanitize_text(value, max_chars=MAX_CONTEXT_VALUE_CHARS)
    if isinstance(value, list):
        if len(value) > MAX_CONTEXT_LIST_ITEMS:
            raise ValidationError(f"context.{key} list exceeds {MAX_CONTEXT_LIST_ITEMS} items")
        return [
            sanitize_text(v, max_chars=MAX_CONTEXT_VALUE_CHARS) if isinstance(v, str) else v
            for v in value
        ]
    raise ValidationError(f"context.{key} has unsupported type {type(value).__name__}")
