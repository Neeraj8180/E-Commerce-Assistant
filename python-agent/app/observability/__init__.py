"""Observability primitives: structured logging, Prometheus metrics, OTel tracing."""

from app.observability.logging import configure_logging, get_logger
from app.observability.metrics import (
    AGENT_FAILURE,
    AGENT_LATENCY,
    AGENT_SUCCESS,
    ESCALATION_TOTAL,
    HALLUCINATION_TOTAL,
    LLM_TOKENS,
    RAG_RETRIEVAL_SCORE,
    TOOL_CALL_LATENCY,
    TOOL_CALL_TOTAL,
)
from app.observability.tracing import init_tracing

__all__ = [
    "configure_logging",
    "get_logger",
    "init_tracing",
    "AGENT_LATENCY",
    "AGENT_SUCCESS",
    "AGENT_FAILURE",
    "TOOL_CALL_TOTAL",
    "TOOL_CALL_LATENCY",
    "LLM_TOKENS",
    "RAG_RETRIEVAL_SCORE",
    "HALLUCINATION_TOTAL",
    "ESCALATION_TOTAL",
]
