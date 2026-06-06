"""Safety / guardrail helpers: escalation, sentiment, grounding checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.observability import ESCALATION_TOTAL, HALLUCINATION_TOTAL, get_logger
from app.tools.policy_rag import RetrievedChunk

log = get_logger(__name__)

_NEGATIVE_SENTIMENT_PATTERNS = [
    re.compile(r"\b(angry|furious|frustrat\w+|ridiculous|terrible|awful|useless|garbage)\b", re.I),
    re.compile(r"\b(this\s+is\s+a\s+joke|waste\s+of\s+time)\b", re.I),
    re.compile(r"!!!+"),
]

_ORDER_ID_RE = re.compile(r"\bORD-\d{3,}\b")
_REFUND_AMOUNT_RE = re.compile(r"\$\s?(\d+(?:\.\d{2})?)")


@dataclass
class GroundingReport:
    grounded: bool
    fabricated_order_ids: list[str]
    unexpected_refund_amounts: list[float]


def is_negative_sentiment(text: str) -> bool:
    return any(p.search(text) for p in _NEGATIVE_SENTIMENT_PATTERNS)


def should_escalate(
    *,
    confidence: float,
    consecutive_failures: int,
    user_message: str,
    refund_amount: float = 0.0,
) -> tuple[bool, str]:
    """Decide whether to escalate to a human agent."""

    if re.search(r"\b(human|agent|person|representative)\b", user_message, re.I) and re.search(
        r"\b(speak|talk|connect|want)\b", user_message, re.I
    ):
        ESCALATION_TOTAL.labels(reason="user_request").inc()
        return True, "user_request"

    if consecutive_failures >= settings.max_failures_before_escalation:
        ESCALATION_TOTAL.labels(reason="repeated_failures").inc()
        return True, "repeated_failures"

    if refund_amount > 500.0:
        ESCALATION_TOTAL.labels(reason="high_value_refund").inc()
        return True, "high_value_refund"

    if is_negative_sentiment(user_message):
        ESCALATION_TOTAL.labels(reason="negative_sentiment").inc()
        return True, "negative_sentiment"

    if confidence < 0.3:
        ESCALATION_TOTAL.labels(reason="low_confidence").inc()
        return True, "low_confidence"

    return False, ""


def check_grounding(
    *,
    intent: str,
    reply: str,
    known_order_ids: list[str],
    known_refund_amounts: list[float],
    rag_chunks: list[RetrievedChunk],
) -> GroundingReport:
    """Verify a reply does not invent order ids or refund amounts.

    Returns a report. Callers can decide to override the reply with a
    safe fallback when ``grounded`` is False.
    """

    fabricated_ids = [oid for oid in _ORDER_ID_RE.findall(reply) if oid not in known_order_ids]

    mentioned_amounts = [float(m) for m in _REFUND_AMOUNT_RE.findall(reply)]
    unexpected_amounts: list[float] = []
    for amt in mentioned_amounts:
        if not any(abs(amt - known) < 0.01 for known in known_refund_amounts):
            unexpected_amounts.append(amt)

    grounded = not fabricated_ids and not unexpected_amounts
    if not grounded:
        HALLUCINATION_TOTAL.labels(intent=intent).inc()
        log.warning(
            "hallucination_detected",
            intent=intent,
            fabricated_order_ids=fabricated_ids,
            unexpected_refund_amounts=unexpected_amounts,
            rag_chunk_count=len(rag_chunks),
        )
    return GroundingReport(
        grounded=grounded,
        fabricated_order_ids=fabricated_ids,
        unexpected_refund_amounts=unexpected_amounts,
    )


def fallback_reply(intent: str, escalated: bool) -> str:
    if escalated:
        return "I'm connecting you with a human agent who can help further. Please hold on."
    return {
        "return": "I'm sorry, I don't have enough information to process that return right now.",
        "exchange": "I'm sorry, I couldn't confirm the exchange. Could you share your order id and the size/colour you'd like?",
        "order_status": "I couldn't find that order. Could you double-check the order id?",
        "general_query": "I don't have enough information on that topic. Would you like to speak with a human agent?",
    }.get(intent, "I'm sorry, I couldn't complete that request right now.")


def extract_order_id(message: str, context: dict[str, Any] | None = None) -> str | None:
    if context and "order_id" in context:
        return str(context["order_id"])
    m = _ORDER_ID_RE.search(message)
    return m.group(0) if m else None
