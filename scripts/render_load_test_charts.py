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
    "concurrency": 100,
    "total": 100,
    "success": 100,
    "p50_ms": 9020,
    "p95_ms": 10291,
    "p99_ms": 10320,
    "avg_ms": 7920,
    "rps": 9.65,
    "status_codes": {"200": 100},
    "query_mix": {"returns": 26, "exchanges": 30, "wismo": 44},
}

LOCAL_RUNS = [
    {
        "label": "5 concurrent",
        "concurrency": 5,
        "total": 30,
        "success": 24,
        "p50_ms": 109884,
        "p95_ms": 179316,
        "p99_ms": 179633,
        "avg_ms": 104768,
        "rps": 0.04,
        "status_codes": {"200": 24, "502": 3, "exception": 3},
    },
    {
        "label": "100 concurrent (stress)",
        "concurrency": 100,
        "total": 100,
        "success": 4,
        "p50_ms": 81402,
        "p95_ms": 81747,
        "p99_ms": 81747,
        "avg_ms": 77772,
        "rps": 0.55,
        "status_codes": {"200": 4, "502": 1, "exception": 95},
    },
]


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
        f"Cloud — Groq ({GROQ_RUN['concurrency']} concurrent users)\n"
        f"{GROQ_RUN['total']} requests · {GROQ_RUN['rps']} req/s · "
        f"mix returns/exchanges/WISMO = {mix['returns']}/{mix['exchanges']}/{mix['wismo']}"
    )
    for bar, val in zip(bars, values):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.02,
            f"{val} ms",
            ha="center",
            fontsize=9,
        )

    codes = GROQ_RUN["status_codes"]
    code_labels = list(codes.keys())
    code_values = list(codes.values())
    colors = ["#16a34a" if k == "200" else "#dc2626" for k in code_labels]
    ax2.bar(code_labels, code_values, color=colors)
    ax2.set_ylabel("Count")
    ax2.set_title(
        f"HTTP status codes — success rate {GROQ_RUN['success'] / GROQ_RUN['total'] * 100:.0f}%"
    )
    for i, val in enumerate(code_values):
        ax2.text(i, val + max(code_values) * 0.02, str(val), ha="center", fontsize=9)

    _save(PROOF / "load-test-groq.png")


def render_local() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    runs = LOCAL_RUNS
    width = 0.35
    x = list(range(4))
    labels = ["p50", "p95", "p99", "avg"]

    series_a = [runs[0]["p50_ms"], runs[0]["p95_ms"], runs[0]["p99_ms"], runs[0]["avg_ms"]]
    series_b = [runs[1]["p50_ms"], runs[1]["p95_ms"], runs[1]["p99_ms"], runs[1]["avg_ms"]]

    ax1.bar([i - width / 2 for i in x], series_a, width, label=runs[0]["label"], color="#2563eb")
    ax1.bar([i + width / 2 for i in x], series_b, width, label=runs[1]["label"], color="#dc2626")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title(
        "Local — Ollama (llama3.2, CPU-only laptop, no GPU)\n"
        f"5-concurrent: {runs[0]['rps']} req/s · 100-concurrent stress: {runs[1]['rps']} req/s"
    )
    ax1.legend()
    for xi, val in zip([i - width / 2 for i in x], series_a):
        ax1.text(xi, val + max(series_a + series_b) * 0.02, f"{val/1000:.0f}s", ha="center", fontsize=8)
    for xi, val in zip([i + width / 2 for i in x], series_b):
        ax1.text(xi, val + max(series_a + series_b) * 0.02, f"{val/1000:.0f}s", ha="center", fontsize=8)

    success_labels = [r["label"] for r in runs]
    success_values = [r["success"] / r["total"] * 100 for r in runs]
    colors = ["#16a34a", "#dc2626"]
    bars = ax2.bar(success_labels, success_values, color=colors)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("Success rate (%)")
    ax2.set_title("Local success rate by concurrency")
    for bar, val, run in zip(bars, success_values, runs):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            val + 2,
            f"{val:.0f}%  ({run['success']}/{run['total']})",
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
