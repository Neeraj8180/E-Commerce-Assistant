"""pgVector-backed session and user memory for multi-turn agent context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.conversations import resolve_user_id
from app.db import get_pool
from app.llm import get_llm_provider
from app.observability import get_logger
from app.validation import MAX_MESSAGE_CHARS, sanitize_text

log = get_logger(__name__)


@dataclass
class MemoryChunk:
    scope: str
    session_id: str | None
    content: str
    score: float
    turn_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "session_id": self.session_id,
            "content": self.content,
            "score": round(self.score, 4),
            "turn_index": self.turn_index,
        }


def build_turn_content(
    *,
    user_message: str,
    assistant_reply: str,
    intent: str,
    outcome: str,
) -> str:
    user = sanitize_text(user_message, max_chars=800)
    assistant = sanitize_text(assistant_reply, max_chars=800)
    return (
        f"User: {user}\n"
        f"Assistant: {assistant}\n"
        f"(intent={intent}, outcome={outcome})"
    )


def format_recent_messages(messages: list[dict[str, Any]], max_turns: int = 3) -> str:
    """Format prior turns (excluding the current user message) for router context."""
    if not messages:
        return ""
    lines: list[str] = []
    for msg in messages[-max_turns * 2 :]:
        role = msg.get("role", "")
        content = sanitize_text(str(msg.get("content", "")), max_chars=300)
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def format_memory_for_prompt(chunks: list[MemoryChunk]) -> str:
    if not chunks:
        return "(no prior conversation memory found)"
    parts: list[str] = []
    for i, ch in enumerate(chunks, 1):
        label = "this session" if ch.scope == "session" else "prior sessions"
        parts.append(f"[{i}] ({label}, score={ch.score:.2f})\n{ch.content}")
    return "\n\n".join(parts)


async def _embed_text(text: str) -> list[float]:
    llm = get_llm_provider()
    embedding = await llm.embed(text)
    if len(embedding) != settings.embed_dimension:
        raise ValueError(
            f"embedding dimension mismatch: got {len(embedding)}, expected {settings.embed_dimension}"
        )
    return embedding


async def index_turn(
    *,
    user_id: str,
    session_id: str,
    user_message: str,
    assistant_reply: str,
    intent: str,
    outcome: str,
    turn_index: int,
) -> None:
    """Persist a completed turn in both session-scoped and user-scoped memory."""
    content = build_turn_content(
        user_message=user_message,
        assistant_reply=assistant_reply,
        intent=intent,
        outcome=outcome,
    )
    if not content.strip():
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        uid = await resolve_user_id(conn, user_id)
        if not uid:
            log.warning("memory_skip_unknown_user", user_id=user_id)
            return

        try:
            embedding = await _embed_text(content)
        except Exception as exc:  # noqa: BLE001
            log.warning("memory_embed_failed", error=str(exc), session_id=session_id)
            return

        vec_literal = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
        meta_json = json.dumps({"intent": intent, "outcome": outcome})

        await conn.execute(
            """
            INSERT INTO memory_embeddings
                (scope, user_id, session_id, turn_index, content, embedding, metadata)
            VALUES ('session', $1::uuid, $2, $3, $4, $5::vector, $6::jsonb)
            ON CONFLICT (session_id, turn_index) WHERE scope = 'session' DO NOTHING
            """,
            uid,
            session_id,
            turn_index,
            content,
            vec_literal,
            meta_json,
        )
        await conn.execute(
            """
            INSERT INTO memory_embeddings
                (scope, user_id, session_id, turn_index, content, embedding, metadata)
            VALUES ('user', $1::uuid, $2, $3, $4, $5::vector, $6::jsonb)
            """,
            uid,
            session_id,
            turn_index,
            content,
            vec_literal,
            meta_json,
        )


async def search_memory(
    query: str,
    *,
    user_id: str,
    session_id: str,
    session_top_k: int | None = None,
    user_top_k: int | None = None,
) -> list[MemoryChunk]:
    """Retrieve relevant session + cross-session user memory for the current turn."""
    query = sanitize_text(query or "", max_chars=MAX_MESSAGE_CHARS)
    if not query:
        return []

    session_k = session_top_k if session_top_k is not None else settings.memory_session_top_k
    user_k = user_top_k if user_top_k is not None else settings.memory_user_top_k
    limit = max(1, min(session_k + user_k, 20))

    pool = get_pool()
    async with pool.acquire() as conn:
        uid = await resolve_user_id(conn, user_id)
        if not uid:
            return []

        try:
            embedding = await _embed_text(query)
        except Exception as exc:  # noqa: BLE001
            log.warning("memory_search_embed_failed", error=str(exc))
            return []

        vec_literal = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
        rows = await conn.fetch(
            """
            SELECT scope, session_id, content, turn_index,
                   1 - (embedding <=> $1::vector) AS score
            FROM memory_embeddings
            WHERE user_id = $2::uuid
              AND (
                    (scope = 'session' AND session_id = $3)
                 OR (scope = 'user' AND (session_id IS DISTINCT FROM $3))
              )
            ORDER BY
                CASE WHEN scope = 'session' THEN 0 ELSE 1 END,
                embedding <=> $1::vector
            LIMIT $4
            """,
            vec_literal,
            uid,
            session_id,
            limit,
        )

    chunks: list[MemoryChunk] = []
    session_count = 0
    user_count = 0
    for r in rows:
        score = float(r["score"])
        if score < settings.memory_score_threshold:
            continue
        scope = r["scope"]
        if scope == "session":
            if session_count >= session_k:
                continue
            session_count += 1
        else:
            if user_count >= user_k:
                continue
            user_count += 1
        chunks.append(
            MemoryChunk(
                scope=scope,
                session_id=r["session_id"],
                content=r["content"],
                score=score,
                turn_index=int(r["turn_index"] or 0),
            )
        )
    return chunks
