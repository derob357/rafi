"""Boundary tests for input handling across all public functions."""

from __future__ import annotations

import pytest

from src.security.sanitizer import sanitize_text, detect_prompt_injection
from src.security.validators import (
    safe_get,
    safe_list_get,
    validate_phone_number,
    validate_email_address,
    validate_datetime_string,
)


@pytest.mark.security
class TestNullInputBoundaries:
    """Test None/null input at every external boundary."""

    def test_sanitize_text_none(self) -> None:
        result = sanitize_text(None, max_length=100)  # type: ignore
        assert result == ""

    def test_sanitize_text_empty(self) -> None:
        result = sanitize_text("", max_length=100)
        assert result == ""

    def test_detect_injection_none(self) -> None:
        result = detect_prompt_injection(None)  # type: ignore
        assert result is False or result is True  # Should not crash

    def test_detect_injection_empty(self) -> None:
        result = detect_prompt_injection("")
        assert result is False

    def test_safe_get_none_dict(self) -> None:
        result = safe_get(None, "key", "default")  # type: ignore
        assert result == "default"

    def test_safe_get_none_key(self) -> None:
        result = safe_get({"a": 1}, None, "default")  # type: ignore
        assert result == "default"

    def test_safe_list_get_none_list(self) -> None:
        result = safe_list_get(None, 0, "default")  # type: ignore
        assert result == "default"

    def test_validate_phone_none(self) -> None:
        result = validate_phone_number(None)  # type: ignore
        assert result is None

    def test_validate_phone_empty(self) -> None:
        result = validate_phone_number("")
        assert result is None

    def test_validate_email_none(self) -> None:
        result = validate_email_address(None)  # type: ignore
        assert result is None

    def test_validate_email_empty(self) -> None:
        result = validate_email_address("")
        assert result is None

    def test_validate_datetime_none(self) -> None:
        result = validate_datetime_string(None)  # type: ignore
        assert result is None

    def test_validate_datetime_empty(self) -> None:
        result = validate_datetime_string("")
        assert result is None


@pytest.mark.security
class TestMaxLengthBoundaries:
    """Test oversized input handling."""

    def test_sanitize_text_max_length(self) -> None:
        long_input = "a" * 10000
        result = sanitize_text(long_input, max_length=100)
        assert len(result) <= 100

    def test_sanitize_text_exactly_max(self) -> None:
        exact_input = "b" * 100
        result = sanitize_text(exact_input, max_length=100)
        assert len(result) == 100

    def test_sanitize_text_one_over_max(self) -> None:
        over_input = "c" * 101
        result = sanitize_text(over_input, max_length=100)
        assert len(result) <= 100

    def test_extremely_long_input(self) -> None:
        """Test with 1MB string — should not crash or hang."""
        mega_input = "x" * (1024 * 1024)
        result = sanitize_text(mega_input, max_length=4096)
        assert len(result) <= 4096


@pytest.mark.security
class TestUnicodeEdgeCases:
    """Test Unicode edge cases."""

    def test_emoji_input(self) -> None:
        result = sanitize_text("Hello 👋🌍🎉", max_length=100)
        assert result is not None
        assert len(result) > 0

    def test_rtl_characters(self) -> None:
        """Right-to-left text should be handled safely."""
        result = sanitize_text("مرحبا بالعالم", max_length=100)
        assert result is not None

    def test_zero_width_characters(self) -> None:
        """Zero-width chars should be stripped."""
        input_with_zw = "hel\u200blo\u200cwo\u200drld\ufeff"
        result = sanitize_text(input_with_zw, max_length=100)
        assert "\u200b" not in result
        assert "\u200c" not in result
        assert "\u200d" not in result
        assert "\ufeff" not in result

    def test_mixed_unicode_scripts(self) -> None:
        result = sanitize_text("Hello Мир 世界 🌍", max_length=100)
        assert result is not None

    def test_combining_characters(self) -> None:
        """Combining diacritical marks."""
        result = sanitize_text("e\u0301 a\u0300", max_length=100)
        assert result is not None

    def test_surrogate_pairs(self) -> None:
        """Emoji requiring surrogate pairs in some encodings."""
        result = sanitize_text("🏳️‍🌈 👨‍👩‍👧‍👦", max_length=100)
        assert result is not None


@pytest.mark.security
class TestNestedNoneInDicts:
    """Test nested None values in dictionaries."""

    def test_nested_none_values(self) -> None:
        data = {"a": None, "b": {"c": None}}
        assert safe_get(data, "a", "default") is None or safe_get(data, "a", "default") == "default"

    def test_missing_nested_key(self) -> None:
        data = {"a": {"b": 1}}
        result = safe_get(data, "nonexistent", {})
        assert result == {}

    def test_deeply_nested_access(self) -> None:
        data = {"a": {"b": {"c": {"d": "value"}}}}
        inner = safe_get(data, "a", {})
        assert isinstance(inner, dict)


@pytest.mark.security
class TestListBoundaries:
    """Test list access boundaries."""

    def test_empty_list_access(self) -> None:
        result = safe_list_get([], 0, "default")
        assert result == "default"

    def test_negative_index(self) -> None:
        result = safe_list_get([1, 2, 3], -1, "default")
        assert result is not None  # Should not crash

    def test_large_index(self) -> None:
        result = safe_list_get([1, 2, 3], 999999, "default")
        assert result == "default"
