"""pgVector-backed retrieval tool for policies and FAQs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.db import get_pool
from app.llm import get_llm_provider
from app.observability import RAG_RETRIEVAL_SCORE
from app.tools._instrument import tool
from app.validation import MAX_MESSAGE_CHARS, ValidationError, sanitize_text


@dataclass
class RetrievedChunk:
    doc_id: str
    doc_type: str
    title: str
    content: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "title": self.title,
            "content": self.content,
            "score": round(self.score, 4),
        }


@tool("search_policies")
async def search_policies(
    query: str,
    top_k: int | None = None,
    doc_type: str | None = None,
) -> list[RetrievedChunk]:
    query = sanitize_text(query or "", max_chars=MAX_MESSAGE_CHARS)
    if not query:
        raise ValidationError("search_policies query is empty")

    k = top_k if top_k is not None else settings.rag_top_k
    if not isinstance(k, int) or k < 1 or k > 25:
        raise ValidationError("top_k must be an integer between 1 and 25")
    if doc_type is not None and doc_type not in ("policy", "faq"):
        raise ValidationError("doc_type must be 'policy' or 'faq'")

    llm = get_llm_provider()
    embedding = await llm.embed(query)
    if len(embedding) != settings.embed_dimension:
        raise ValidationError(
            f"embedding dimension mismatch: got {len(embedding)}, expected {settings.embed_dimension}"
        )
    vec_literal = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

    where = ""
    params: list[Any] = [vec_literal, k]
    if doc_type:
        where = "WHERE doc_type = $3"
        params.append(doc_type)

    sql = f"""
        SELECT doc_id, doc_type, title, content,
               1 - (embedding <=> $1::vector) AS score
        FROM embeddings
        {where}
        ORDER BY embedding <=> $1::vector ASC
        LIMIT $2
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results: list[RetrievedChunk] = []
    for r in rows:
        score = float(r["score"])
        RAG_RETRIEVAL_SCORE.labels(doc_type=r["doc_type"]).observe(max(0.0, score))
        if score >= settings.rag_score_threshold:
            results.append(
                RetrievedChunk(
                    doc_id=r["doc_id"],
                    doc_type=r["doc_type"],
                    title=r["title"] or "",
                    content=r["content"],
                    score=score,
                )
            )
    return results


def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no relevant policy or FAQ content found)"
    return "\n\n".join(
        f"[{i}] ({ch.doc_id} — {ch.title})\n{ch.content}" for i, ch in enumerate(chunks, 1)
    )


def chunks_to_metadata(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    return [ch.to_dict() for ch in chunks]


def chunks_to_json(chunks: list[RetrievedChunk]) -> str:
    return json.dumps(chunks_to_metadata(chunks))
