"""Tests for src/security/validators.py — safe getters and data validators.

Covers:
- safe_get with valid / missing / None keys
- safe_list_get with valid / out-of-bounds indexes
- validate_phone_number with valid / invalid formats
- validate_email_address with valid / invalid formats
- validate_datetime_string with valid / invalid formats
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Import validators — stub if source not yet written.
# ---------------------------------------------------------------------------
try:
    from src.security.validators import (
        safe_get,
        safe_list_get,
        validate_phone_number,
        validate_email_address,
        validate_datetime_string,
    )
except ImportError:
    def safe_get(d, key, default=None):  # type: ignore[misc]
        raise NotImplementedError("src.security.validators.safe_get not yet implemented")

    def safe_list_get(lst, index, default=None):  # type: ignore[misc]
        raise NotImplementedError("src.security.validators.safe_list_get not yet implemented")

    def validate_phone_number(phone):  # type: ignore[misc]
        raise NotImplementedError("src.security.validators.validate_phone_number not yet implemented")

    def validate_email_address(email):  # type: ignore[misc]
        raise NotImplementedError("src.security.validators.validate_email_address not yet implemented")

    def validate_datetime_string(dt_str):  # type: ignore[misc]
        raise NotImplementedError("src.security.validators.validate_datetime_string not yet implemented")


# ===================================================================
# safe_get
# ===================================================================


class TestSafeGet:
    """safe_get retrieves dictionary values safely."""

    def test_existing_key(self):
        d = {"name": "Alice", "age": 30}
        assert safe_get(d, "name") == "Alice"

    def test_missing_key_returns_default(self):
        d = {"name": "Alice"}
        assert safe_get(d, "missing") is None

    def test_missing_key_custom_default(self):
        d = {"name": "Alice"}
        assert safe_get(d, "missing", "fallback") == "fallback"

    def test_none_value_returned(self):
        d = {"key": None}
        result = safe_get(d, "key", "default")
        # Should return None (the actual value), not the default
        assert result is None

    def test_empty_dict(self):
        assert safe_get({}, "anything") is None

    def test_empty_string_key(self):
        d = {"": "empty_key_value"}
        assert safe_get(d, "") == "empty_key_value"

    def test_nested_key_not_traversed(self):
        """safe_get is single-level; nested dicts are returned as-is."""
        d = {"outer": {"inner": "value"}}
        result = safe_get(d, "outer")
        assert isinstance(result, dict)
        assert result["inner"] == "value"

    def test_none_dict_handled(self):
        """Passing None as the dict should not crash."""
        try:
            result = safe_get(None, "key", "default")  # type: ignore[arg-type]
            assert result == "default"
        except (TypeError, AttributeError):
            pass  # acceptable: refusing None input

    def test_integer_value(self):
        d = {"count": 42}
        assert safe_get(d, "count") == 42

    def test_boolean_false_value(self):
        d = {"active": False}
        assert safe_get(d, "active") is False


# ===================================================================
# safe_list_get
# ===================================================================


class TestSafeListGet:
    """safe_list_get retrieves list elements safely."""

    def test_valid_index(self):
        lst = ["a", "b", "c"]
        assert safe_list_get(lst, 0) == "a"
        assert safe_list_get(lst, 2) == "c"

    def test_negative_index(self):
        lst = ["a", "b", "c"]
        assert safe_list_get(lst, -1) == "c"

    def test_out_of_bounds_returns_default(self):
        lst = ["a", "b", "c"]
        assert safe_list_get(lst, 5) is None

    def test_out_of_bounds_custom_default(self):
        lst = ["a", "b", "c"]
        assert safe_list_get(lst, 99, "fallback") == "fallback"

    def test_empty_list(self):
        assert safe_list_get([], 0) is None

    def test_empty_list_custom_default(self):
        assert safe_list_get([], 0, "nothing") == "nothing"

    def test_none_list_handled(self):
        try:
            result = safe_list_get(None, 0, "default")  # type: ignore[arg-type]
            assert result == "default"
        except (TypeError, AttributeError):
            pass  # acceptable

    def test_single_element_list(self):
        assert safe_list_get([42], 0) == 42
        assert safe_list_get([42], 1) is None


# ===================================================================
# validate_phone_number
# ===================================================================


class TestValidatePhoneNumber:
    """Phone number validation accepts E.164 and rejects invalid formats."""

    @pytest.mark.parametrize(
        "phone",
        [
            "+15551234567",
            "+442071234567",
            "+81312345678",
            "+1234567890",
        ],
    )
    def test_valid_phones(self, phone: str):
        assert validate_phone_number(phone) is True

    @pytest.mark.parametrize(
        "phone",
        [
            "5551234567",         # missing +
            "+1",                 # too short
            "not-a-phone",        # text
            "",                   # empty
            "+1-555-123-4567",    # dashes not E.164
            "+1 555 123 4567",    # spaces not E.164
            "(555) 123-4567",     # US formatted
        ],
    )
    def test_invalid_phones(self, phone: str):
        assert validate_phone_number(phone) is False

    def test_none_phone(self):
        try:
            result = validate_phone_number(None)  # type: ignore[arg-type]
            assert result is False
        except (TypeError, AttributeError):
            pass  # acceptable


# ===================================================================
# validate_email_address
# ===================================================================


class TestValidateEmailAddress:
    """Email address validation accepts valid and rejects invalid formats."""

    @pytest.mark.parametrize(
        "email",
        [
            "user@example.com",
            "first.last@company.org",
            "user+tag@example.co.uk",
            "test123@sub.domain.com",
        ],
    )
    def test_valid_emails(self, email: str):
        assert validate_email_address(email) is True

    @pytest.mark.parametrize(
        "email",
        [
            "not-an-email",
            "@example.com",
            "user@",
            "user@.com",
            "",
            "user@com",
            "user space@example.com",
            "user@@example.com",
        ],
    )
    def test_invalid_emails(self, email: str):
        assert validate_email_address(email) is False

    def test_none_email(self):
        try:
            result = validate_email_address(None)  # type: ignore[arg-type]
            assert result is False
        except (TypeError, AttributeError):
            pass


# ===================================================================
# validate_datetime_string
# ===================================================================


class TestValidateDatetimeString:
    """Datetime string validation accepts ISO-8601 and rejects garbage."""

    @pytest.mark.parametrize(
        "dt_str",
        [
            "2025-06-15T09:00:00-04:00",
            "2025-06-15T09:00:00Z",
            "2025-06-15T09:00:00+00:00",
            "2025-06-15T09:00:00",
            "2025-06-15",
        ],
    )
    def test_valid_datetime_strings(self, dt_str: str):
        assert validate_datetime_string(dt_str) is True

    @pytest.mark.parametrize(
        "dt_str",
        [
            "not-a-date",
            "tomorrow",
            "06/15/2025",
            "",
            "2025-13-01T00:00:00",   # month 13
            "2025-06-32T00:00:00",   # day 32
        ],
    )
    def test_invalid_datetime_strings(self, dt_str: str):
        assert validate_datetime_string(dt_str) is False

    def test_none_datetime(self):
        try:
            result = validate_datetime_string(None)  # type: ignore[arg-type]
            assert result is False
        except (TypeError, AttributeError):
            pass
