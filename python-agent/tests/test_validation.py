import pytest

from app.validation import (
    ValidationError,
    is_idempotency_key,
    is_order_id,
    is_session_id,
    is_sku,
    require_refund_amount,
    sanitize_text,
    validate_context,
    validate_item_skus,
)


def test_order_id_pattern():
    assert is_order_id("ORD-1001")
    assert is_order_id("ORD-123456")
    assert not is_order_id("ORD-")
    assert not is_order_id("ord-1001")
    assert not is_order_id("OTHER-1001")
    assert not is_order_id(None)


def test_sku_pattern():
    assert is_sku("TSHIRT-BLU-M")
    assert is_sku("MUG-CER-WHT")
    assert not is_sku("t-shirt")
    assert not is_sku("")
    assert not is_sku("A!")


def test_session_id_pattern():
    assert is_session_id("eval-ret-001-abc123")
    assert not is_session_id("bad session id")
    assert not is_session_id("a" * 129)


def test_idempotency_key():
    assert is_idempotency_key("a" * 16)
    assert not is_idempotency_key("short")
    assert not is_idempotency_key("a" * 200)


def test_require_refund_amount():
    assert require_refund_amount(42) == 42.00
    assert require_refund_amount(42.499) == 42.50
    with pytest.raises(ValidationError):
        require_refund_amount(-1)
    with pytest.raises(ValidationError):
        require_refund_amount(0)
    with pytest.raises(ValidationError):
        require_refund_amount(10_000_000)
    with pytest.raises(ValidationError):
        require_refund_amount(float("inf"))


def test_sanitize_text_strips_controls_and_caps_length():
    raw = "hello\x00world\u0007"
    cleaned = sanitize_text(raw, max_chars=100)
    assert "\x00" not in cleaned
    assert "\u0007" not in cleaned
    assert cleaned == "helloworld"


def test_sanitize_text_truncates():
    long = "a" * 5000
    cleaned = sanitize_text(long, max_chars=100)
    assert len(cleaned) <= 101  # may include the ellipsis


def test_validate_item_skus_dedupes_and_uppercases():
    out = validate_item_skus(["tshirt-blu-m", "TSHIRT-BLU-M", "MUG-CER-WHT"])
    assert out == ["TSHIRT-BLU-M", "MUG-CER-WHT"]


def test_validate_item_skus_rejects_bad_sku():
    with pytest.raises(ValidationError):
        validate_item_skus(["not a sku"])


def test_validate_context_accepts_basic_types():
    out = validate_context({"order_id": "ORD-1001", "amount": 12.5, "active": True})
    assert out["order_id"] == "ORD-1001"
    assert out["amount"] == 12.5
    assert out["active"] is True


def test_validate_context_rejects_bad_key():
    with pytest.raises(ValidationError):
        validate_context({"BAD KEY": "x"})


def test_validate_context_rejects_nested_object():
    with pytest.raises(ValidationError):
        validate_context({"k": {"nested": "obj"}})


def test_validate_context_rejects_too_many_keys():
    with pytest.raises(ValidationError):
        validate_context({f"k{i}": i for i in range(50)})
