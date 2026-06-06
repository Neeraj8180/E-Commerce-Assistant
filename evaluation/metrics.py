"""Scoring logic for the evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CaseScore:
    case_id: str
    intent_correct: bool
    outcome_correct: bool
    tools_correct: bool
    grounded: bool
    latency_score: float
    composite: float
    failure_reasons: list[str]
    actual_intent: str
    actual_outcome: str
    actual_tools: list[str]
    latency_ms: int


def score_latency(latency_ms: int) -> float:
    """Map latency to a [0, 1] score per the plan: <1s=1.0, <2.5s=0.5, else 0."""
    if latency_ms < 1000:
        return 1.0
    if latency_ms < 2500:
        return 0.5
    return 0.0


def score_case(
    expected: dict[str, Any],
    actual: dict[str, Any],
    latency_ms: int,
) -> CaseScore:
    intent_ok = expected["expected_intent"] == actual.get("intent")
    outcome_ok = expected["expected_outcome"] == actual.get("outcome")

    expected_tools = set(expected.get("expected_tools", []))
    actual_tools = list(actual.get("tools_used", []))
    actual_tools_set = set(actual_tools)
    # Tools correct if every expected tool was called (extra calls don't penalize).
    tools_ok = expected_tools.issubset(actual_tools_set)

    grounding_meta = (actual.get("metadata") or {}).get("grounding")
    grounded = grounding_meta is None

    latency_score = score_latency(latency_ms)

    composite = (
        0.30 * float(intent_ok)
        + 0.30 * float(outcome_ok)
        + 0.20 * latency_score
        + 0.10 * float(grounded)
        + 0.10 * float(tools_ok)
    )

    reasons: list[str] = []
    if not intent_ok:
        reasons.append(f"wrong_routing: expected {expected['expected_intent']}, got {actual.get('intent')}")
    if not outcome_ok:
        reasons.append(f"wrong_outcome: expected {expected['expected_outcome']}, got {actual.get('outcome')}")
    if not tools_ok:
        missing = expected_tools - actual_tools_set
        if missing:
            reasons.append(f"missing_tools: {sorted(missing)}")
    if not grounded:
        reasons.append("hallucination_detected")
    if latency_score < 1.0:
        reasons.append(f"slow_latency: {latency_ms}ms")

    return CaseScore(
        case_id=expected["id"],
        intent_correct=intent_ok,
        outcome_correct=outcome_ok,
        tools_correct=tools_ok,
        grounded=grounded,
        latency_score=latency_score,
        composite=round(composite, 3),
        failure_reasons=reasons,
        actual_intent=actual.get("intent", ""),
        actual_outcome=actual.get("outcome", ""),
        actual_tools=actual_tools,
        latency_ms=latency_ms,
    )


def aggregate(scores: list[CaseScore]) -> dict[str, Any]:
    total = len(scores)
    if total == 0:
        return {
            "total": 0,
            "intent_accuracy": 0.0,
            "task_success_rate": 0.0,
            "tool_correctness": 0.0,
            "grounded_rate": 0.0,
            "hallucination_rate": 0.0,
            "avg_latency_ms": 0.0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "p99_latency_ms": 0,
            "composite_score": 0.0,
        }
    intent_acc = sum(1 for s in scores if s.intent_correct) / total
    task_success = sum(1 for s in scores if s.outcome_correct) / total
    tools_acc = sum(1 for s in scores if s.tools_correct) / total
    grounded_rate = sum(1 for s in scores if s.grounded) / total
    hallucination_rate = 1.0 - grounded_rate
    avg_latency = sum(s.latency_ms for s in scores) / total
    composite = sum(s.composite for s in scores) / total
    latency_sorted = sorted(s.latency_ms for s in scores)
    p50 = latency_sorted[min(int(total * 0.50), total - 1)]
    p95 = latency_sorted[min(int(total * 0.95), total - 1)]
    p99 = latency_sorted[min(int(total * 0.99), total - 1)]
    return {
        "total": total,
        "intent_accuracy": round(intent_acc, 3),
        "task_success_rate": round(task_success, 3),
        "tool_correctness": round(tools_acc, 3),
        "grounded_rate": round(grounded_rate, 3),
        "hallucination_rate": round(hallucination_rate, 3),
        "avg_latency_ms": round(avg_latency, 1),
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
        "composite_score": round(composite, 3),
    }
