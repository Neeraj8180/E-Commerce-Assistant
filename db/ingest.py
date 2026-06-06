"""
Ingest policy and FAQ documents into the pgVector `embeddings` table.

Run inside the python-agent container:
    docker compose run --rm python-agent python -m db.ingest

Behavior:
    * Loads ``db/seed/policies.json``.
    * Chunks long documents into ~512 token windows with 50 token overlap.
    * Generates embeddings via the configured LLM provider (Ollama by default).
    * Upserts into ``embeddings`` (unique on doc_id + chunk_index).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg

# Make the python-agent package importable when running via `python -m db.ingest`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python-agent"))

from app.config import settings  # noqa: E402
from app.llm import get_llm_provider  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

# Approximate token chunking using a simple word-based heuristic.
# Avoids a tiktoken dependency in this script.
CHUNK_WORDS = 380           # ~512 tokens for English prose
CHUNK_OVERLAP_WORDS = 40    # ~50 token overlap


def chunk_text(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    chunks: list[str] = []
    step = size - overlap
    for start in range(0, len(words), step):
        chunk = " ".join(words[start:start + size])
        if chunk:
            chunks.append(chunk)
        if start + size >= len(words):
            break
    return chunks


async def ingest() -> None:
    seed_path = Path(__file__).parent / "seed" / "policies.json"
    docs: list[dict[str, Any]] = json.loads(seed_path.read_text())["policies"]
    log.info("loaded %d source documents from %s", len(docs), seed_path)

    llm = get_llm_provider()
    conn = await asyncpg.connect(settings.database_url)
    try:
        total_chunks = 0
        for doc in docs:
            chunks = chunk_text(doc["content"])
            for idx, chunk in enumerate(chunks):
                embedding = await llm.embed(chunk)
                if len(embedding) != settings.embed_dimension:
                    raise RuntimeError(
                        f"Embedding dimension mismatch: got {len(embedding)}, "
                        f"expected {settings.embed_dimension}. "
                        f"Update EMBED_DIMENSION env var or the embeddings table schema."
                    )
                # pgvector accepts the bracketed list literal as text via cast.
                vec_literal = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
                await conn.execute(
                    """
                    INSERT INTO embeddings (doc_type, doc_id, chunk_index, title, content, embedding, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
                    ON CONFLICT (doc_id, chunk_index)
                    DO UPDATE SET content = EXCLUDED.content,
                                  embedding = EXCLUDED.embedding,
                                  title = EXCLUDED.title,
                                  metadata = EXCLUDED.metadata
                    """,
                    doc["type"],
                    doc["id"],
                    idx,
                    doc.get("title", ""),
                    chunk,
                    vec_literal,
                    json.dumps({"source": "seed/policies.json"}),
                )
                total_chunks += 1
            log.info("ingested %s (%d chunks)", doc["id"], len(chunks))
        log.info("done. %d chunks across %d documents", total_chunks, len(docs))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(ingest())
