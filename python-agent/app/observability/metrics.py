"""Prometheus metric definitions."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# Latency histograms use buckets aligned with the system SLOs (p50 < 1s, p95 < 2.5s).
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.5, 5.0, 10.0)

AGENT_LATENCY = Histogram(
    "agent_latency_seconds",
    "End-to-end agent processing latency.",
    labelnames=("agent_name", "intent"),
    buckets=_LATENCY_BUCKETS,
)

AGENT_SUCCESS = Counter(
    "agent_success_total",
    "Successful agent invocations.",
    labelnames=("agent_name", "intent"),
)

AGENT_FAILURE = Counter(
    "agent_failure_total",
    "Failed agent invocations.",
    labelnames=("agent_name", "reason"),
)

TOOL_CALL_TOTAL = Counter(
    "tool_call_total",
    "Tool invocations from agents.",
    labelnames=("tool_name", "status"),
)

TOOL_CALL_LATENCY = Histogram(
    "tool_call_latency_seconds",
    "Latency of agent tool invocations.",
    labelnames=("tool_name",),
    buckets=_LATENCY_BUCKETS,
)

LLM_TOKENS = Counter(
    "llm_token_usage_total",
    "Tokens consumed by the LLM provider.",
    labelnames=("model", "kind"),
)

RAG_RETRIEVAL_SCORE = Histogram(
    "rag_retrieval_score",
    "Cosine similarity scores returned by the RAG retriever.",
    labelnames=("doc_type",),
    buckets=(0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
)

HALLUCINATION_TOTAL = Counter(
    "hallucination_total",
    "Responses flagged as hallucinations by guardrails.",
    labelnames=("intent",),
)

ESCALATION_TOTAL = Counter(
    "escalation_total",
    "Conversations escalated to a human agent.",
    labelnames=("reason",),
)
