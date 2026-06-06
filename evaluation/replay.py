"""Conversation replay CLI.

Usage:
    docker compose run --rm python-agent python -m evaluation.replay --session-id <id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python-agent"))

GO_SERVER_URL = os.getenv("EVAL_GO_SERVER_URL", "http://go-server:8080")
API_KEY = os.getenv("API_KEY", "")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Replay a stored conversation.")
    ap.add_argument("--session-id", required=True)
    args = ap.parse_args()

    if not API_KEY:
        print("ERROR: API_KEY env var must be set", file=sys.stderr)
        return 1
    headers = {"X-API-Key": API_KEY}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{GO_SERVER_URL}/replay",
            json={"session_id": args.session_id},
            headers=headers,
        )
        if resp.status_code >= 400:
            print(f"ERROR {resp.status_code}: {resp.text}", file=sys.stderr)
            return 1
        print(json.dumps(resp.json(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
