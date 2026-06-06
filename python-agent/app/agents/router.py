"""Router agent: classifies user intent into a fixed taxonomy.

Approach:
    1. Fast regex rules cover the common phrasings (high precision, zero LLM cost).
    2. If rules are inconclusive, an LLM classifier produces JSON output.

The two-stage design keeps p50 latency low and reduces LLM token spend.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Literal

from app.llm import get_llm_provider
from app.observability import AGENT_LATENCY, AGENT_SUCCESS, LLM_TOKENS, get_logger

Intent = Literal["return", "exchange", "order_status", "general_query", "escalate_to_human"]

VALID_INTENTS: tuple[str, ...] = (
    "return",
    "exchange",
    "order_status",
    "general_query",
    "escalate_to_human",
)

log = get_logger(__name__)


@dataclass
class RouterResult:
    intent: Intent
    confidence: float
    source: Literal["rule", "llm"]
    rationale: str = ""


# Order matters: most specific patterns first.
_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    ("escalate_to_human", re.compile(r"\b(speak|talk|connect)\s+to\s+(a\s+)?(human|agent|person|representative)\b", re.I)),
    ("escalate_to_human", re.compile(r"\b(human\s+agent|live\s+agent|customer\s+service)\b", re.I)),
    ("exchange", re.compile(r"\b(exchange|swap|replace)\b.*\b(size|color|colour|item|product|order)\b", re.I)),
    ("exchange", re.compile(r"\b(different|another|new)\s+(size|color|colour)\b", re.I)),
    ("return", re.compile(r"\b(return|refund|send\s+back|give\s+back)\b", re.I)),
    ("order_status", re.compile(r"\b(where\s+is\s+my\s+order|wismo|track(ing)?|shipment|when\s+will\s+it\s+(arrive|be\s+delivered))\b", re.I)),
    ("order_status", re.compile(r"\b(order\s+status|delivery\s+status|tracking\s+number)\b", re.I)),
]


_SYSTEM_PROMPT = (
    "You are an e-commerce intent classifier. "
    "Classify the user's message into exactly one of: return, exchange, order_status, "
    "general_query, escalate_to_human. "
    "Return strict JSON: {\"intent\": <one of the labels>, \"confidence\": <0..1>, \"rationale\": <short>}. "
    "Do not output anything else."
)


def _rule_classify(message: str) -> RouterResult | None:
    for intent, pattern in _RULES:
        if pattern.search(message):
            return RouterResult(intent=intent, confidence=0.95, source="rule", rationale=f"matched /{pattern.pattern}/")
    return None


async def _llm_classify(message: str, recent_context: str = "") -> RouterResult:
    llm = get_llm_provider()
    context_block = ""
    if recent_context.strip():
        context_block = f"Recent conversation:\n{recent_context}\n\n"
    prompt = f"{context_block}User message: {message!r}\nClassify and respond with JSON only."
    resp = await llm.complete(prompt, system=_SYSTEM_PROMPT, temperature=0.0, json_mode=True)
    LLM_TOKENS.labels(model=resp.model, kind="prompt").inc(resp.prompt_tokens)
    LLM_TOKENS.labels(model=resp.model, kind="completion").inc(resp.completion_tokens)

    intent: Intent = "general_query"
    confidence = 0.5
    rationale = "fallback"
    try:
        data = json.loads(resp.text)
        candidate = str(data.get("intent", "")).strip().lower().replace(" ", "_")
        if candidate in VALID_INTENTS:
            intent = candidate  # type: ignore[assignment]
            raw_conf = float(data.get("confidence", 0.7))
            if raw_conf != raw_conf or raw_conf in (float("inf"), float("-inf")):
                raw_conf = 0.5
            confidence = max(0.0, min(1.0, raw_conf))
            rationale = str(data.get("rationale", ""))[:200]
    except (ValueError, TypeError) as exc:
        log.warning("router_llm_parse_failed", error=str(exc), raw=resp.text[:200])

    return RouterResult(intent=intent, confidence=confidence, source="llm", rationale=rationale)


class RouterAgent:
    name = "router"

    async def classify(self, message: str, recent_context: str = "") -> RouterResult:
        start = time.perf_counter()
        result = _rule_classify(message)
        if result is None:
            result = await _llm_classify(message, recent_context=recent_context)
        AGENT_LATENCY.labels(agent_name=self.name, intent=result.intent).observe(time.perf_counter() - start)
        AGENT_SUCCESS.labels(agent_name=self.name, intent=result.intent).inc()
        log.info(
            "router_classified",
            intent=result.intent,
            confidence=result.confidence,
            source=result.source,
        )
        return result
