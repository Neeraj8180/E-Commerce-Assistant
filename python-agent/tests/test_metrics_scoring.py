"""Tests for the evaluation scoring logic."""

import sys
from pathlib import Path

# Make sibling evaluation/ importable when pytest runs from python-agent/.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.metrics import aggregate, score_case, score_latency  # noqa: E402


def test_score_latency_thresholds():
    assert score_latency(500) == 1.0
    assert score_latency(1500) == 0.5
    assert score_latency(3000) == 0.0


def test_score_case_perfect():
    expected = {
        "id": "t1",
        "expected_intent": "return",
        "expected_outcome": "approved_auto",
        "expected_tools": ["get_order", "shopify_create_return"],
    }
    actual = {
        "intent": "return",
        "outcome": "approved_auto",
        "tools_used": ["get_order", "search_policies", "shopify_create_return"],
        "metadata": {},
    }
    s = score_case(expected, actual, latency_ms=500)
    assert s.intent_correct
    assert s.outcome_correct
    assert s.tools_correct
    assert s.grounded
    assert s.composite == 1.0


def test_score_case_hallucination():
    expected = {"id": "t2", "expected_intent": "return", "expected_outcome": "ok", "expected_tools": []}
    actual = {
        "intent": "return", "outcome": "ok", "tools_used": [],
        "metadata": {"grounding": {"fabricated_order_ids": ["ORD-9"]}},
    }
    s = score_case(expected, actual, latency_ms=500)
    assert not s.grounded
    assert "hallucination_detected" in s.failure_reasons


def test_aggregate_empty():
    summary = aggregate([])
    assert summary["total"] == 0
