"""Quick RAG smoke test.

Usage (inside the python-agent container):
    docker compose run --rm python-agent python -m db.rag_smoke "How long is the return window?"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python-agent"))

from app.db import close_pool, init_pool  # noqa: E402
from app.tools.policy_rag import search_policies  # noqa: E402


async def main(query: str) -> None:
    await init_pool()
    try:
        chunks = await search_policies(query, top_k=5)
        if not chunks:
            print(f"No chunks above similarity threshold for: {query!r}")
            return
        print(f"Top {len(chunks)} chunks for: {query!r}\n")
        for c in chunks:
            print(f"  [{c.score:.3f}] {c.doc_id} ({c.doc_type}) — {c.title}")
            preview = c.content[:160].replace("\n", " ")
            print(f"        {preview}...")
            print()
    finally:
        await close_pool()


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "How long is the return window?"
    asyncio.run(main(query))
