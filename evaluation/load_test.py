"""Concurrent load test against the running stack.

Fires N parallel /chat requests (default 100) using the synthetic eval datasets
to stress-test gateway concurrency, agent throughput, memory indexing, and
circuit-breaker behaviour.

Usage:
    docker compose run --rm python-agent python -m evaluation.load_test
    docker compose run --rm python-agent python -m evaluation.load_test --concurrency 100 --dataset returns
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python-agent"))

from evaluation.runner import DATASETS, load_dataset  # noqa: E402

GO_SERVER_URL = os.getenv("EVAL_GO_SERVER_URL", "http://go-server:8080")
API_KEY = os.getenv("API_KEY", "")


@dataclass
class RequestResult:
    case_id: str
    user_id: str
    status: str
    http_status: int = 0
    latency_ms: int = 0
    intent: str = ""
    outcome: str = ""
    error: str = ""
    memory_used: bool = False


@dataclass
class LoadSummary:
    concurrency: int
    dataset: str
    total: int
    success: int
    errors: int
    success_rate: float
    avg_latency_ms: float
    p50_latency_ms: int
    p95_latency_ms: int
    p99_latency_ms: int
    duration_ms: int
    requests_per_second: float
    status_codes: dict[str, int] = field(default_factory=dict)
    error_samples: list[str] = field(default_factory=list)


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(int(len(ordered) * pct), len(ordered) - 1)
    return ordered[idx]


async def _one_request(
    client: httpx.AsyncClient,
    case: dict[str, Any],
    sem: asyncio.Semaphore,
) -> RequestResult:
    async with sem:
        session_id = f"load-{case['id']}-{uuid.uuid4().hex[:8]}"
        payload = {
            "session_id": session_id,
            "message": case["query"],
            "context": case.get("context", {}),
        }
        headers = {"X-API-Key": API_KEY, "X-User-ID": case["user_id"]}
        start = time.perf_counter()
        try:
            resp = await client.post(f"{GO_SERVER_URL}/chat", json=payload, headers=headers)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if resp.status_code >= 400:
                return RequestResult(
                    case_id=case["id"],
                    user_id=case["user_id"],
                    status="error",
                    http_status=resp.status_code,
                    latency_ms=latency_ms,
                    error=resp.text[:200],
                )
            body = resp.json()
            memory_meta = (body.get("metadata") or {}).get("memory") or {}
            return RequestResult(
                case_id=case["id"],
                user_id=case["user_id"],
                status="ok",
                http_status=resp.status_code,
                latency_ms=latency_ms,
                intent=body.get("intent", ""),
                outcome=body.get("outcome", ""),
                memory_used=bool(memory_meta.get("count")),
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - start) * 1000)
            return RequestResult(
                case_id=case["id"],
                user_id=case["user_id"],
                status="error",
                latency_ms=latency_ms,
                error=str(exc)[:200],
            )


def _summarize(
    results: list[RequestResult],
    *,
    concurrency: int,
    dataset: str,
    duration_ms: int,
) -> LoadSummary:
    total = len(results)
    ok = [r for r in results if r.status == "ok"]
    errs = [r for r in results if r.status != "ok"]
    latencies = [r.latency_ms for r in ok]
    codes: dict[str, int] = {}
    for r in results:
        key = str(r.http_status) if r.http_status else "exception"
        codes[key] = codes.get(key, 0) + 1
    duration_s = max(duration_ms / 1000.0, 0.001)
    return LoadSummary(
        concurrency=concurrency,
        dataset=dataset,
        total=total,
        success=len(ok),
        errors=len(errs),
        success_rate=round(len(ok) / total, 3) if total else 0.0,
        avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        p99_latency_ms=_percentile(latencies, 0.99),
        duration_ms=duration_ms,
        requests_per_second=round(total / duration_s, 2),
        status_codes=codes,
        error_samples=[f"{r.case_id}: {r.error}" for r in errs[:10]],
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description="Concurrent load test for the e-commerce agent stack.")
    ap.add_argument("--dataset", choices=["returns", "exchanges", "wismo", "all"], default="all")
    ap.add_argument("--concurrency", type=int, default=100, help="Parallel in-flight requests")
    ap.add_argument("--limit", type=int, default=100, help="Number of cases to fire (capped by dataset size)")
    ap.add_argument("--timeout", type=float, default=180.0, help="Per-request HTTP timeout (seconds)")
    ap.add_argument("--output-dir", default=str(ROOT / "evaluation" / "reports"))
    args = ap.parse_args()

    if not API_KEY:
        print("ERROR: API_KEY env var is required", file=sys.stderr)
        return 1

    cases = load_dataset(args.dataset)[: args.limit]
    if not cases:
        print("ERROR: no cases loaded", file=sys.stderr)
        return 1

    concurrency = max(1, min(args.concurrency, len(cases)))
    print(f"Load test: {len(cases)} requests, concurrency={concurrency}, target={GO_SERVER_URL}")

    sem = asyncio.Semaphore(concurrency)
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        results = await asyncio.gather(*[_one_request(client, c, sem) for c in cases])
    duration_ms = int((time.perf_counter() - start) * 1000)

    summary = _summarize(results, concurrency=concurrency, dataset=args.dataset, duration_ms=duration_ms)
    print("\nLoad test summary:")
    for k, v in summary.__dict__.items():
        if k != "error_samples":
            print(f"  {k}: {v}")
    if summary.error_samples:
        print("  error_samples:")
        for sample in summary.error_samples:
            print(f"    - {sample}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"load-test-{args.dataset}-{ts}.json"
    path.write_text(
        json.dumps(
            {
                "summary": summary.__dict__,
                "results": [r.__dict__ for r in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {path}")
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
