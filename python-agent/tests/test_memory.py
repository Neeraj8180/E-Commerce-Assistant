"""Unit tests for conversation memory helpers."""

from app.memory import MemoryChunk, build_turn_content, format_memory_for_prompt, format_recent_messages


def test_build_turn_content():
    text = build_turn_content(
        user_message="Where is ORD-1004?",
        assistant_reply="Your order is in transit.",
        intent="order_status",
        outcome="in_transit",
    )
    assert "User: Where is ORD-1004?" in text
    assert "Assistant: Your order is in transit." in text
    assert "intent=order_status" in text


def test_format_recent_messages():
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Track ORD-1001"},
    ]
    recent = format_recent_messages(messages, max_turns=2)
    assert "user: Track ORD-1001" in recent
    assert "assistant: Hello" in recent


def test_format_memory_for_prompt_empty():
    assert "no prior conversation memory" in format_memory_for_prompt([])


def test_format_memory_for_prompt_with_chunks():
    chunks = [
        MemoryChunk(scope="session", session_id="s1", content="User: hi\nAssistant: hello", score=0.82, turn_index=1),
        MemoryChunk(scope="user", session_id="s0", content="User: old\nAssistant: noted", score=0.71, turn_index=2),
    ]
    text = format_memory_for_prompt(chunks)
    assert "this session" in text
    assert "prior sessions" in text
    assert "User: hi" in text
