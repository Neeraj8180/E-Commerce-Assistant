"""Render proof charts for the load-test results.

Produces two PNGs under docs/proof/:
    load-test-groq.png   — Groq 100-concurrent run
    load-test-local.png  — Local Ollama runs at 5 and 100 concurrent

Numbers are baked in from the actual runs captured earlier so the charts
stay stable even if reports are pruned.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs" / "proof"


GROQ_RUN = {
    "label": "Groq (llama-3.3-70b-versatile)",
    "concurrency": 30,
    "total": 30,
    "http_200": 30,
    "real_success": 5,
    "fallback": 25,
    "p50_ms": 15657,
    "p95_ms": 16079,
    "p99_ms": 16100,
    "avg_ms": 14426,
    "rps": 1.86,
    "query_mix": {"returns": 9, "exchanges": 8, "wismo": 13},
}

LOCAL_RUN = {
    "label": "Local Ollama (llama3.2, CPU-only)",
    "concurrency": 5,
    "total": 30,
    "http_200": 24,
    "real_success": 24,
    "p50_ms": 109884,
    "p95_ms": 179316,
    "p99_ms": 179633,
    "avg_ms": 104768,
    "rps": 0.04,
    "errors": 6,
}


def _save(path: Path) -> None:
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"created {path}")


def render_groq() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    labels = ["p50", "p95", "p99", "avg"]
    values = [GROQ_RUN["p50_ms"], GROQ_RUN["p95_ms"], GROQ_RUN["p99_ms"], GROQ_RUN["avg_ms"]]
    bars = ax1.bar(labels, values, color=["#16a34a", "#2563eb", "#7c3aed", "#0f766e"])
    ax1.set_ylabel("Latency (ms)")
    mix = GROQ_RUN["query_mix"]
    ax1.set_title(
        f"Groq burst stress — {GROQ_RUN['concurrency']} concurrent users (free tier)\n"
        f"{GROQ_RUN['total']} simultaneous requests · {GROQ_RUN['rps']} req/s · "
        f"mix returns/exchanges/WISMO = {mix['returns']}/{mix['exchanges']}/{mix['wismo']}"
    )
    for bar, val in zip(bars, values):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.02,
            f"{val/1000:.1f}s",
            ha="center",
            fontsize=9,
        )

    outcome_labels = ["Real outcome", "Graceful fallback\n(429 \u2192 retry \u2192 degrade)"]
    outcome_values = [GROQ_RUN["real_success"], GROQ_RUN["fallback"]]
    colors = ["#16a34a", "#f59e0b"]
    bars2 = ax2.bar(outcome_labels, outcome_values, color=colors)
    ax2.set_ylabel("Requests")
    ax2.set_title(
        f"Outcome split — all 30 returned HTTP 200, no crashes\n"
        f"upstream free-tier RPM cap absorbed {GROQ_RUN['fallback']}/{GROQ_RUN['total']} via graceful degradation"
    )
    for bar, val in zip(bars2, outcome_values):
        pct = val / GROQ_RUN["total"] * 100
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            val + max(outcome_values) * 0.03,
            f"{val}  ({pct:.0f}%)",
            ha="center",
            fontsize=10,
        )

    _save(PROOF / "load-test-groq.png")


def render_local() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    run = LOCAL_RUN
    labels = ["p50", "p95", "p99", "avg"]
    values = [run["p50_ms"], run["p95_ms"], run["p99_ms"], run["avg_ms"]]
    bars = ax1.bar(labels, values, color=["#2563eb", "#7c3aed", "#dc2626", "#0f766e"])
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title(
        f"Local Ollama — {run['concurrency']} concurrent, {run['total']} requests\n"
        f"{run['rps']} req/s   (llama3.2 on CPU, no GPU)"
    )
    for bar, val in zip(bars, values):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.02,
            f"{val/1000:.0f}s",
            ha="center",
            fontsize=9,
        )

    outcome_labels = ["Real outcome", "Timeout / 5xx"]
    outcome_values = [run["real_success"], run["errors"]]
    colors = ["#16a34a", "#dc2626"]
    bars2 = ax2.bar(outcome_labels, outcome_values, color=colors)
    ax2.set_ylabel("Requests")
    ax2.set_title(
        f"Outcome split — {run['real_success']}/{run['total']} real successes ({run['real_success']/run['total']*100:.0f}%)"
    )
    for bar, val in zip(bars2, outcome_values):
        pct = val / run["total"] * 100
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            val + max(outcome_values) * 0.03,
            f"{val}  ({pct:.0f}%)",
            ha="center",
            fontsize=10,
        )

    _save(PROOF / "load-test-local.png")


def main() -> int:
    PROOF.mkdir(parents=True, exist_ok=True)
    render_groq()
    render_local()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
