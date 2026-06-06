"""Conversation persistence helpers (read/write to the ``conversations`` table)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db import get_pool
from app.validation import MAX_MESSAGES_PER_CONVERSATION, sanitize_text


async def load_conversation(session_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM conversations WHERE session_id = $1", session_id)
        if row is None:
            return None
        return _row_to_dict(row)


async def upsert_conversation(
    *,
    session_id: str,
    user_id: str | None,
    intent: str,
    outcome: str,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    escalated: bool,
) -> None:
    if len(messages) > MAX_MESSAGES_PER_CONVERSATION:
        messages = messages[-MAX_MESSAGES_PER_CONVERSATION:]
    pool = get_pool()
    async with pool.acquire() as conn:
        uid = await _resolve_user_uuid(conn, user_id)
        await conn.execute(
            """
            INSERT INTO conversations (session_id, user_id, intent, outcome, messages, metadata, escalated)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
            ON CONFLICT (session_id)
            DO UPDATE SET
                user_id   = COALESCE(EXCLUDED.user_id, conversations.user_id),
                intent    = EXCLUDED.intent,
                outcome   = EXCLUDED.outcome,
                messages  = EXCLUDED.messages,
                metadata  = EXCLUDED.metadata,
                escalated = EXCLUDED.escalated
            """,
            session_id,
            uid,
            intent,
            outcome,
            json.dumps(messages, default=str),
            json.dumps(metadata, default=str),
            escalated,
        )


async def _resolve_user_uuid(conn, user_id: str | None) -> str | None:
    if not user_id:
        return None
    # If already a UUID, accept it.
    if len(user_id) == 36 and user_id.count("-") == 4:
        return user_id
    # Look up by email.
    row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", user_id)
    return str(row["id"]) if row else None


def append_message(messages: list[dict[str, Any]], role: str, content: str, meta: dict[str, Any] | None = None) -> None:
    if role not in {"user", "assistant", "system"}:
        raise ValueError(f"invalid message role: {role!r}")
    safe_content = sanitize_text(content or "", max_chars=4000)
    messages.append(
        {
            "role": role,
            "content": safe_content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **({"meta": meta} if meta else {}),
        }
    )


def _row_to_dict(row) -> dict[str, Any]:
    msgs = row["messages"]
    if isinstance(msgs, str):
        msgs = json.loads(msgs)
    md = row["metadata"]
    if isinstance(md, str):
        md = json.loads(md)
    return {
        "id": str(row["id"]),
        "session_id": row["session_id"],
        "user_id": str(row["user_id"]) if row["user_id"] else None,
        "intent": row["intent"],
        "outcome": row["outcome"],
        "messages": msgs,
        "metadata": md,
        "escalated": row["escalated"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
