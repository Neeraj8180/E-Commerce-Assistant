"""Capture proof artifacts for README: eval charts, Prometheus metrics, Grafana dashboards."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs" / "proof"
REPORTS = ROOT / "evaluation" / "reports"

PROM = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
GRAFANA = os.getenv("GRAFANA_URL", "http://localhost:3000")
GO_API = os.getenv("GO_API_URL", "http://localhost:8080")


def _save_fig(name: str) -> Path:
    PROOF.mkdir(parents=True, exist_ok=True)
    path = PROOF / name
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    return path


def latest_eval_json() -> Path | None:
    files = sorted(REPORTS.glob("eval-all-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def chart_eval_summary() -> Path | None:
    path = latest_eval_json()
    if path is None:
        print("no eval json found, skipping eval chart")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary") or data
    labels = [
        "Intent accuracy",
        "Task success",
        "Tool correctness",
        "Grounded rate",
        "Composite",
    ]
    keys = [
        "intent_accuracy",
        "task_success_rate",
        "tool_correctness",
        "grounded_rate",
        "composite_score",
    ]
    values = [float(summary.get(k, 0)) * 100 for k in keys]
    colors = ["#2563eb", "#16a34a", "#7c3aed", "#ea580c", "#0f766e"]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Score (%)")
    ax.set_title(
        f"Evaluation summary — {summary.get('total', '?')} cases "
        f"(avg latency {summary.get('avg_latency_ms', 0):.0f} ms)"
    )
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{val:.1f}%", ha="center", fontsize=9)
    return _save_fig("eval-summary.png")


def chart_eval_by_category() -> Path | None:
    path = latest_eval_json()
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("scores") or data.get("cases") or []
    buckets: dict[str, list[float]] = {"return": [], "exchange": [], "order_status": []}
    for c in rows:
        cid = c.get("case_id") or c.get("id") or ""
        if cid.startswith("ret-"):
            key = "return"
        elif cid.startswith("exc-"):
            key = "exchange"
        elif cid.startswith("wis-"):
            key = "order_status"
        else:
            key = c.get("actual_intent") or "other"
        if key in buckets:
            buckets[key].append(float(c.get("composite", 0)))
    labels = ["Returns", "Exchanges", "WISMO"]
    keys = ["return", "exchange", "order_status"]
    avgs = [sum(buckets[k]) / len(buckets[k]) * 100 if buckets[k] else 0 for k in keys]
    counts = [len(buckets[k]) for k in keys]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, avgs, color=["#dc2626", "#2563eb", "#059669"])
    ax.set_ylim(0, 105)
    ax.set_ylabel("Avg composite score (%)")
    ax.set_title("Eval composite score by agent scope")
    for bar, val, cnt in zip(bars, avgs, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{val:.1f}% ({cnt})", ha="center", fontsize=9)
    return _save_fig("eval-by-scope.png")


def prom_query(query: str) -> float:
    try:
        r = httpx.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=10)
        r.raise_for_status()
        result = r.json()["data"]["result"]
        if not result:
            return 0.0
        return float(result[0]["value"][1])
    except Exception:
        return 0.0


def chart_prometheus_metrics() -> Path:
    metrics = {
        "Agent successes": prom_query('sum(agent_success_total)'),
        "Agent failures": prom_query('sum(agent_failure_total)'),
        "Tool calls": prom_query('sum(tool_call_total)'),
        "LLM prompt tokens": prom_query('sum(llm_token_usage_total{kind="prompt"})'),
        "LLM completion tokens": prom_query('sum(llm_token_usage_total{kind="completion"})'),
        "Escalations": prom_query('sum(escalation_total)'),
        "Hallucination flags": prom_query('sum(hallucination_total)'),
    }
    fig, ax = plt.subplots(figsize=(10, 5))
    names = list(metrics.keys())
    vals = list(metrics.values())
    bars = ax.barh(names, vals, color="#1d4ed8")
    ax.set_title("Prometheus metrics snapshot (live stack)")
    for bar, val in zip(bars, vals):
        ax.text(bar.get_width() + max(vals) * 0.01, bar.get_y() + bar.get_height() / 2, f"{int(val)}", va="center", fontsize=9)
    return _save_fig("prometheus-metrics.png")


def latest_load_test_json() -> Path | None:
    files = sorted(REPORTS.glob("load-test-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def chart_load_test() -> Path | None:
    path = latest_load_test_json()
    if path is None:
        print("no load-test json found, skipping load-test chart")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    s = data.get("summary") or {}
    if not s:
        return None

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    labels = ["p50", "p95", "p99", "avg"]
    values = [s.get("p50_latency_ms", 0), s.get("p95_latency_ms", 0),
              s.get("p99_latency_ms", 0), s.get("avg_latency_ms", 0)]
    bars = ax1.bar(labels, values, color=["#16a34a", "#2563eb", "#7c3aed", "#0f766e"])
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title(
        f"Load test — {s.get('concurrency', '?')} concurrent users\n"
        f"{s.get('total', '?')} requests · {s.get('requests_per_second', 0):.1f} req/s"
    )
    for bar, val in zip(bars, values):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.02,
                 f"{int(val)} ms", ha="center", fontsize=9)

    codes = s.get("status_codes", {}) or {}
    if codes:
        code_labels = list(codes.keys())
        code_values = list(codes.values())
        colors = ["#16a34a" if k == "200" else "#dc2626" for k in code_labels]
        ax2.bar(code_labels, code_values, color=colors)
        ax2.set_ylabel("Count")
        ax2.set_title(
            f"HTTP status codes (success rate {s.get('success_rate', 0) * 100:.1f}%)"
        )
        for i, val in enumerate(code_values):
            ax2.text(i, val + max(code_values) * 0.02, str(val), ha="center", fontsize=9)
    else:
        ax2.axis("off")

    return _save_fig("load-test.png")


def chart_latency_histogram() -> Path | None:
    path = latest_eval_json()
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    latencies = [int(c.get("latency_ms", 0)) for c in data.get("scores", data.get("cases", [])) if c.get("latency_ms")]
    if not latencies:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(latencies, bins=20, color="#7c3aed", edgecolor="white")
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Cases")
    ax.set_title(f"Eval latency distribution (n={len(latencies)}, p50={sorted(latencies)[len(latencies)//2]} ms)")
    return _save_fig("eval-latency.png")


def screenshot_grafana_dashboards() -> list[Path]:
    saved: list[Path] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed; skipping Grafana screenshots")
        return saved

    dashboards = [
        ("ecom-agent-perf", "grafana-agent-performance.png"),
        ("ecom-agent-latency", "grafana-latency-failures.png"),
    ]
    PROOF.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        for dash_uid, filename in dashboards:
            url = f"{GRAFANA}/d/{dash_uid}"
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(3)
                out = PROOF / filename
                page.screenshot(path=str(out), full_page=True)
                saved.append(out)
                print(f"screenshot {out}")
            except Exception as exc:
                print(f"grafana {dash_uid} failed: {exc}")
        # Prometheus graph UI
        try:
            page.goto(f"{PROM}/graph", wait_until="networkidle", timeout=20000)
            time.sleep(2)
            out = PROOF / "prometheus-ui.png"
            page.screenshot(path=str(out), full_page=True)
            saved.append(out)
        except Exception as exc:
            print(f"prometheus ui failed: {exc}")
        browser.close()
    return saved


def render_chat_demo_card() -> Path:
    """Render a sample successful API response as a proof card."""
    try:
        login = httpx.post(
            f"{GO_API}/auth/login",
            json={"email": "alice@example.com", "password": "alice-pass-2026"},
            timeout=15,
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        chat = httpx.post(
            f"{GO_API}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Where is my order ORD-1004?", "context": {"order_id": "ORD-1004"}},
            timeout=120,
        )
        chat.raise_for_status()
        payload = chat.json()
    except Exception as exc:
        payload = {"error": str(exc)}

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis("off")
    text = (
        "Live API demo — WISMO (ORD-1004)\n\n"
        f"intent:    {payload.get('intent', 'n/a')}\n"
        f"outcome:   {payload.get('outcome', 'n/a')}\n"
        f"latency:   {payload.get('latency_ms', 'n/a')} ms\n"
        f"tools:     {', '.join(payload.get('tools_used') or [])}\n"
        f"escalated: {payload.get('escalated', 'n/a')}\n\n"
        f"reply:\n{payload.get('reply', payload.get('error', ''))[:400]}"
    )
    ax.text(0.02, 0.98, text, va="top", family="monospace", fontsize=10, wrap=True)
    ax.set_title("Go API /chat — authenticated end-to-end response", fontsize=12, fontweight="bold")
    return _save_fig("chat-demo-wismo.png")


def render_architecture_card() -> Path:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.axis("off")
    flow = (
        "User → Go Gateway (JWT, validation) → Python Agents (Router / Q&A / Planner)\n"
        "     → Tools (orders, RAG, Shopify, Stripe) → PostgreSQL + pgVector + Kafka\n"
        "     → OpenTelemetry / Prometheus / Grafana\n\n"
        "Scopes: Returns · Exchanges · WISMO (100 eval cases each)\n"
        "Memory: session + user pgVector · Load test: 100 concurrent users"
    )
    ax.text(0.5, 0.5, flow, ha="center", va="center", fontsize=11, family="sans-serif",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#eff6ff", edgecolor="#2563eb"))
    ax.set_title("E-Commerce Agentic AI — system proof", fontsize=13, fontweight="bold")
    return _save_fig("architecture-proof.png")


def screenshot_eval_html() -> Path | None:
    html_files = sorted(REPORTS.glob("eval-all-*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not html_files:
        return None
    html = html_files[0]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    PROOF.mkdir(parents=True, exist_ok=True)
    out = PROOF / "eval-report.png"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(html.resolve().as_uri(), wait_until="load", timeout=20000)
        time.sleep(1)
        page.screenshot(path=str(out), full_page=True)
        browser.close()
    return out


def main() -> int:
    PROOF.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for fn in (render_architecture_card, chart_eval_summary, chart_eval_by_category,
               chart_latency_histogram, chart_prometheus_metrics, chart_load_test,
               render_chat_demo_card):
        try:
            p = fn()
            if p:
                created.append(p)
                print(f"created {p}")
        except Exception as exc:
            print(f"{fn.__name__} failed: {exc}", file=sys.stderr)
    created.extend(screenshot_grafana_dashboards())
    try:
        p = screenshot_eval_html()
        if p:
            created.append(p)
            print(f"created {p}")
    except Exception as exc:
        print(f"eval html screenshot failed: {exc}", file=sys.stderr)
    manifest = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "files": [p.name for p in created]}
    (PROOF / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"proof artifacts: {len(created)} files in {PROOF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
