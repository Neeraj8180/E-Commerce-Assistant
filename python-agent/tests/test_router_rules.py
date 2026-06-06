"""Tests for the rule-based portion of the Router agent (no LLM, no I/O)."""

from app.agents.router import _rule_classify


def test_return_keyword():
    r = _rule_classify("Can I return my order?")
    assert r is not None and r.intent == "return"


def test_exchange_with_size():
    r = _rule_classify("I want to exchange this for a different size")
    assert r is not None and r.intent == "exchange"


def test_wismo_phrase():
    r = _rule_classify("where is my order ORD-1004")
    assert r is not None and r.intent == "order_status"


def test_human_request():
    r = _rule_classify("Please connect me to a human agent")
    assert r is not None and r.intent == "escalate_to_human"


def test_unknown_falls_through_to_llm():
    r = _rule_classify("hello, how are you today?")
    assert r is None
