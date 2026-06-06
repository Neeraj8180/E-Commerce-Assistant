"""Render Groq-specific proof charts from an eval-harness JSON report.

Produces under docs/proof/ (all with a -groq suffix so local proofs are
untouched):
    eval-summary-groq.png      bar chart of headline metrics
    eval-by-scope-groq.png     composite score per agent scope
    eval-latency-groq.png      latency histogram
    eval-report-groq.png       text card mirroring the HTML report header

Usage:
    python scripts/render_groq_eval_charts.py \
        --eval-json evaluation/reports/eval-all-YYYYMMDD-HHMMSS.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs" / "proof"
REPORTS = ROOT / "evaluation" / "reports"


def _save(fig: plt.Figure, name: str) -> Path:
    PROOF.mkdir(parents=True, exist_ok=True)
    path = PROOF / name
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {path}")
    return path


def latest_eval() -> Path | None:
    files = sorted(REPORTS.glob("eval-all-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def render_summary(data: dict) -> None:
    summary = data.get("summary", {})
    labels = ["Intent\naccuracy", "Task\nsuccess", "Tool\ncorrectness", "Grounded\nrate", "Composite"]
    keys = ["intent_accuracy", "task_success_rate", "tool_correctness", "grounded_rate", "composite_score"]
    values = [float(summary.get(k, 0)) * 100 for k in keys]
    colors = ["#2563eb", "#16a34a", "#7c3aed", "#ea580c", "#0f766e"]

    fig, ax = plt.subplots(figsize=(9, 5.2))
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Score (%)")
    avg_lat = summary.get("avg_latency_ms", 0)
    ax.set_title(
        f"Groq eval summary — {summary.get('total', '?')} cases, "
        f"avg latency {avg_lat:,.0f} ms ({avg_lat/1000:.1f} s)"
    )
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{val:.1f}%", ha="center", fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "eval-summary-groq.png")


def render_by_scope(data: dict) -> None:
    scores = data.get("scores", [])
    buckets = {"return": [], "exchange": [], "order_status": []}
    for s in scores:
        cid = s.get("case_id", "")
        if cid.startswith("ret-"):
            buckets["return"].append(float(s.get("composite", 0)))
        elif cid.startswith("exc-"):
            buckets["exchange"].append(float(s.get("composite", 0)))
        elif cid.startswith("wis-"):
            buckets["order_status"].append(float(s.get("composite", 0)))

    labels = ["Returns", "Exchanges", "WISMO"]
    keys = ["return", "exchange", "order_status"]
    avgs = [sum(buckets[k]) / len(buckets[k]) * 100 if buckets[k] else 0 for k in keys]
    counts = [len(buckets[k]) for k in keys]

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    bars = ax.bar(labels, avgs, color=["#dc2626", "#2563eb", "#059669"])
    ax.set_ylim(0, 110)
    ax.set_ylabel("Avg composite score (%)")
    ax.set_title("Groq eval — composite score by agent scope")
    for bar, val, cnt in zip(bars, avgs, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{val:.1f}%  (n={cnt})", ha="center", fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "eval-by-scope-groq.png")


def render_latency(data: dict) -> None:
    latencies = [int(s.get("latency_ms", 0)) for s in data.get("scores", []) if s.get("latency_ms")]
    if not latencies:
        return
    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2]
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]

    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.hist(latencies, bins=25, color="#7c3aed", edgecolor="white")
    ax.axvline(p50, color="#16a34a", linestyle="--", label=f"p50 = {p50/1000:.1f} s")
    ax.axvline(p95, color="#dc2626", linestyle="--", label=f"p95 = {p95/1000:.1f} s")
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Cases")
    ax.set_title(f"Groq eval latency distribution (n={len(latencies)})")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "eval-latency-groq.png")


def render_report_card(data: dict) -> None:
    summary = data.get("summary", {})
    scores = data.get("scores", [])
    fails = sum(1 for s in scores if s.get("failure_reasons"))
    passes = len(scores) - fails

    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.axis("off")
    rows = [
        ("LLM provider", "Groq · llama-3.3-70b-versatile"),
        ("Embeddings", "nomic-embed-text via Ollama"),
        ("Total cases", str(summary.get("total", 0))),
        ("Pass / Fail", f"{passes} / {fails}"),
        ("Intent accuracy", f"{summary.get('intent_accuracy', 0)*100:.1f}%"),
        ("Task success rate", f"{summary.get('task_success_rate', 0)*100:.1f}%"),
        ("Tool correctness", f"{summary.get('tool_correctness', 0)*100:.1f}%"),
        ("Grounded rate", f"{summary.get('grounded_rate', 0)*100:.1f}%"),
        ("Composite score", f"{summary.get('composite_score', 0):.3f}"),
        ("Avg latency", f"{summary.get('avg_latency_ms', 0):,.0f} ms"),
        ("p50 latency", f"{summary.get('p50_latency_ms', 0):,.0f} ms"),
        ("p95 latency", f"{summary.get('p95_latency_ms', 0):,.0f} ms"),
    ]
    text = "\n".join(f"  {k:<22} {v}" for k, v in rows)
    ax.text(0.02, 0.97, "Groq — full eval harness report", fontsize=14, fontweight="bold", va="top")
    ax.text(0.02, 0.90, text, family="monospace", fontsize=11, va="top")
    ax.text(0.02, 0.04,
            "300 synthetic cases (100 returns + 100 exchanges + 100 WISMO).\n"
            "Same Go gateway, agents, validation, circuit breaker, pgVector memory as local run.",
            fontsize=9, style="italic", va="bottom", color="#475569")
    _save(fig, "eval-report-groq.png")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render Groq-specific eval proof charts.")
    ap.add_argument("--eval-json", type=str, default="", help="Path to eval-all-*.json (defaults to latest)")
    args = ap.parse_args()

    path = Path(args.eval_json) if args.eval_json else latest_eval()
    if not path or not path.exists():
        print("ERROR: no eval JSON found", file=sys.stderr)
        return 1
    print(f"reading {path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    render_summary(data)
    render_by_scope(data)
    render_latency(data)
    render_report_card(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
