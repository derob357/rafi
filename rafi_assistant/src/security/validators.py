"""Safe accessor and validation utility functions.

Provides null-safe access helpers and input validators that return
Optional values instead of raising exceptions on invalid input.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# E.164 phone number pattern: + followed by 1-15 digits
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

# Basic email pattern (RFC 5322 simplified)
EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

# Common datetime formats to try when parsing
DATETIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
]


def safe_get(data: Optional[dict[str, Any]], key: str, default: T = None) -> Any:  # type: ignore[assignment]
    """Safely get a value from a dictionary.

    Args:
        data: Dictionary to access. Returns default if None.
        key: Key to look up.
        default: Default value if key is missing or data is None.

    Returns:
        The value for the key, or the default value.
    """
    if data is None:
        return default
    if not isinstance(data, dict):
        logger.warning("safe_get called with non-dict type: %s", type(data).__name__)
        return default
    return data.get(key, default)


def safe_list_get(data: Optional[list[Any]], index: int, default: T = None) -> Any:  # type: ignore[assignment]
    """Safely get a value from a list by index.

    Args:
        data: List to access. Returns default if None.
        index: Index to look up.
        default: Default value if index is out of range or data is None.

    Returns:
        The value at the index, or the default value.
    """
    if data is None:
        return default
    if not isinstance(data, list):
        logger.warning("safe_list_get called with non-list type: %s", type(data).__name__)
        return default
    if index < 0 or index >= len(data):
        return default
    return data[index]


def validate_phone_number(phone: Optional[str]) -> Optional[str]:
    """Validate a phone number in E.164 format.

    Args:
        phone: Phone number string to validate.

    Returns:
        The phone number if valid, None otherwise.
    """
    if phone is None:
        return None
    if not isinstance(phone, str):
        logger.warning("validate_phone_number received non-string: %s", type(phone).__name__)
        return None

    phone = phone.strip()
    if PHONE_PATTERN.match(phone):
        return phone

    logger.debug("Invalid phone number format: %s", phone[:4] + "***")
    return None


def validate_email_address(email: Optional[str]) -> Optional[str]:
    """Validate an email address format.

    Args:
        email: Email address string to validate.

    Returns:
        The email address if valid, None otherwise.
    """
    if email is None:
        return None
    if not isinstance(email, str):
        logger.warning("validate_email_address received non-string: %s", type(email).__name__)
        return None

    email = email.strip().lower()
    if len(email) > 254:
        logger.debug("Email address exceeds maximum length: %d", len(email))
        return None

    if EMAIL_PATTERN.match(email):
        return email

    logger.debug("Invalid email address format")
    return None


def validate_datetime_string(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse a datetime string in various common formats.

    Tries multiple datetime formats and returns the first successful parse.

    Args:
        dt_str: Datetime string to parse.

    Returns:
        A datetime object if parsing succeeds, None otherwise.
    """
    if dt_str is None:
        return None
    if not isinstance(dt_str, str):
        logger.warning("validate_datetime_string received non-string: %s", type(dt_str).__name__)
        return None

    dt_str = dt_str.strip()
    if not dt_str:
        return None

    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

    logger.debug("Could not parse datetime string: %s", dt_str[:30])
    return None


def validate_positive_int(value: Any, field_name: str = "value") -> Optional[int]:
    """Validate that a value is a positive integer.

    Args:
        value: The value to validate.
        field_name: Name of the field for logging purposes.

    Returns:
        The integer value if positive, None otherwise.
    """
    if value is None:
        return None
    try:
        int_val = int(value)
    except (ValueError, TypeError):
        logger.debug("Cannot convert %s to int for field '%s'", value, field_name)
        return None

    if int_val <= 0:
        logger.debug("Field '%s' must be positive, got %d", field_name, int_val)
        return None

    return int_val


def validate_non_empty_string(value: Optional[str], field_name: str = "value") -> Optional[str]:
    """Validate that a string is non-empty after stripping whitespace.

    Args:
        value: The string to validate.
        field_name: Name of the field for logging purposes.

    Returns:
        The stripped string if non-empty, None otherwise.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        logger.debug("Field '%s' is not a string: %s", field_name, type(value).__name__)
        return None

    stripped = value.strip()
    if not stripped:
        logger.debug("Field '%s' is empty after stripping", field_name)
        return None

    return stripped
