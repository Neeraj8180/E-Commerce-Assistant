"""Batch evaluation runner.

Usage (inside the python-agent container with the stack running):
    docker compose run --rm python-agent python -m evaluation.runner --dataset all
    docker compose run --rm python-agent python -m evaluation.runner --dataset returns --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python-agent"))

from app.db import close_pool, init_pool  # noqa: E402
from evaluation.metrics import CaseScore, aggregate, score_case  # noqa: E402

DATASETS = {
    "returns": ROOT / "evaluation" / "dataset" / "returns.jsonl",
    "exchanges": ROOT / "evaluation" / "dataset" / "exchanges.jsonl",
    "wismo": ROOT / "evaluation" / "dataset" / "wismo.jsonl",
}

GO_SERVER_URL = os.getenv("EVAL_GO_SERVER_URL", "http://go-server:8080")
API_KEY = os.getenv("API_KEY", "")


def load_dataset(name: str) -> list[dict[str, Any]]:
    if name == "all":
        cases: list[dict[str, Any]] = []
        for n in DATASETS:
            cases.extend(load_dataset(n))
        return cases
    path = DATASETS[name]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_case(client: httpx.AsyncClient, case: dict[str, Any]) -> tuple[dict[str, Any], int]:
    # Identity comes from the X-User-ID header on service tokens; the request
    # body deliberately does not accept user_id (would allow impersonation).
    payload = {
        "session_id": f"eval-{case['id']}-{uuid.uuid4().hex[:6]}",
        "message": case["query"],
        "context": case.get("context", {}),
    }
    if not API_KEY:
        raise RuntimeError("API_KEY env var is required to run the eval harness")
    headers = {"X-API-Key": API_KEY, "X-User-ID": case["user_id"]}
    start = time.perf_counter()
    resp = await client.post(f"{GO_SERVER_URL}/chat", json=payload, headers=headers)
    latency_ms = int((time.perf_counter() - start) * 1000)
    resp.raise_for_status()
    return resp.json(), latency_ms


async def write_eval_run(dataset_name: str, summary: dict[str, Any], failures: list[dict[str, Any]]) -> None:
    """Persist a row in the eval_runs table for later inspection."""
    try:
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO eval_runs (dataset_name, total_queries, scores, failures, notes)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
                """,
                dataset_name,
                summary["total"],
                json.dumps(summary),
                json.dumps(failures),
                f"runner={GO_SERVER_URL}",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not persist eval run: {exc}", file=sys.stderr)


def render_html_report(summary: dict[str, Any], scores: list[CaseScore], dataset_name: str) -> str:
    rows = []
    for s in scores:
        row_class = "ok" if not s.failure_reasons else "fail"
        rows.append(
            f"<tr class='{row_class}'>"
            f"<td>{s.case_id}</td>"
            f"<td>{s.actual_intent}</td>"
            f"<td>{s.actual_outcome}</td>"
            f"<td>{s.latency_ms} ms</td>"
            f"<td>{s.composite}</td>"
            f"<td>{'; '.join(s.failure_reasons) or '-'}</td>"
            "</tr>"
        )
    summary_items = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in summary.items())
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Eval — {dataset_name}</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; font-size: 14px; }}
tr.fail {{ background: #fff4f4; }}
tr.ok {{ background: #f4fff4; }}
ul {{ list-style: none; padding: 0; }}
ul li {{ display: inline-block; margin-right: 1rem; }}
</style></head>
<body>
<h1>E-Commerce Agent — {dataset_name}</h1>
<ul>{summary_items}</ul>
<table>
<thead><tr><th>Case</th><th>Intent</th><th>Outcome</th><th>Latency</th><th>Score</th><th>Failures</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>
"""


async def main() -> int:
    ap = argparse.ArgumentParser(description="Run evaluation against the running e-commerce agent system.")
    ap.add_argument("--dataset", choices=["returns", "exchanges", "wismo", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="Only run the first N cases (0 = all)")
    ap.add_argument("--output-dir", default=str(ROOT / "evaluation" / "reports"))
    args = ap.parse_args()

    cases = load_dataset(args.dataset)
    if args.limit > 0:
        cases = cases[: args.limit]
    print(f"Running {len(cases)} cases against {GO_SERVER_URL}")

    await init_pool()
    scores: list[CaseScore] = []
    failures: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for case in cases:
                try:
                    actual, latency_ms = await run_case(client, case)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {case['id']}: ERROR {exc}")
                    failures.append({"id": case["id"], "error": str(exc)})
                    continue
                score = score_case(case, actual, latency_ms)
                scores.append(score)
                status = "PASS" if not score.failure_reasons else "FAIL"
                print(f"  {case['id']}: {status} ({latency_ms} ms) - {score.composite}")
                if score.failure_reasons:
                    failures.append({**dataclasses.asdict(score), "expected": case})

        summary = aggregate(scores) if scores else {"total": 0}
        print("\nSummary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")

        await write_eval_run(args.dataset, summary, failures)

        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        json_path = out_dir / f"eval-{args.dataset}-{ts}.json"
        html_path = out_dir / f"eval-{args.dataset}-{ts}.html"
        json_path.write_text(json.dumps({"summary": summary, "failures": failures,
                                          "scores": [dataclasses.asdict(s) for s in scores]}, indent=2))
        html_path.write_text(render_html_report(summary, scores, args.dataset))
        print(f"\nWrote {json_path}\nWrote {html_path}")
    finally:
        await close_pool()

    return 0 if all(s.intent_correct for s in scores) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
