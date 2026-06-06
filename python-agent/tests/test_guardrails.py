"""Unit tests for pure guardrail helpers (no I/O)."""

from app.guardrails import (
    check_grounding,
    extract_order_id,
    is_negative_sentiment,
    should_escalate,
)


def test_is_negative_sentiment():
    assert is_negative_sentiment("This is ridiculous and useless!")
    assert not is_negative_sentiment("Thanks for your help.")


def test_extract_order_id_from_message():
    assert extract_order_id("Where is ORD-1234?") == "ORD-1234"
    assert extract_order_id("no order here") is None
    assert extract_order_id("anything", {"order_id": "ORD-9"}) == "ORD-9"


def test_escalation_user_request():
    escalate, reason = should_escalate(
        confidence=0.9, consecutive_failures=0,
        user_message="please connect me to a human agent",
    )
    assert escalate
    assert reason == "user_request"


def test_escalation_repeated_failures():
    escalate, reason = should_escalate(
        confidence=0.9, consecutive_failures=3,
        user_message="help me",
    )
    assert escalate
    assert reason == "repeated_failures"


def test_escalation_high_value_refund():
    escalate, reason = should_escalate(
        confidence=0.9, consecutive_failures=0,
        user_message="refund please", refund_amount=750.0,
    )
    assert escalate
    assert reason == "high_value_refund"


def test_grounding_flags_fabricated_order_id():
    rep = check_grounding(
        intent="return",
        reply="Your refund for ORD-9999 has been processed.",
        known_order_ids=["ORD-1001"],
        known_refund_amounts=[],
        rag_chunks=[],
    )
    assert not rep.grounded
    assert "ORD-9999" in rep.fabricated_order_ids


def test_grounding_accepts_known_refund_amount():
    rep = check_grounding(
        intent="return",
        reply="A refund of $42.00 has been issued for ORD-1001.",
        known_order_ids=["ORD-1001"],
        known_refund_amounts=[42.00],
        rag_chunks=[],
    )
    assert rep.grounded
