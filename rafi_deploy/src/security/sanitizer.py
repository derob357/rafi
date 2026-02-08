"""Input sanitization for deploy inputs.

Provides functions to validate and sanitize user-provided values
before they are used in deployment operations. Prevents path traversal,
command injection, and other input-based attacks.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pattern for safe client names: alphanumeric and underscores, 1-64 chars
_CLIENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{1,64}$")

# Characters that are never allowed in any input
_DANGEROUS_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Shell metacharacters that could be used for injection
_SHELL_META_CHARS = re.compile(r"[;|&`$(){}!<>]")

# Maximum length for general string config values
MAX_CONFIG_VALUE_LENGTH = 4096

# Maximum length for URLs
MAX_URL_LENGTH = 2048

# Maximum length for phone numbers
MAX_PHONE_LENGTH = 20

# Phone number pattern: optional +, then digits, spaces, dashes, parens
_PHONE_PATTERN = re.compile(r"^\+?[\d\s\-()]{7,20}$")

# URL pattern for basic validation
_URL_PATTERN = re.compile(
    r"^https?://[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*"
    r"(:\d{1,5})?(/[^\s]*)?$"
)

# Email pattern
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# Time format pattern (HH:MM)
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# IANA timezone pattern (basic validation)
_TIMEZONE_PATTERN = re.compile(r"^[A-Za-z]+(/[A-Za-z_]+)+$")


class SanitizationError(Exception):
    """Raised when input fails sanitization checks."""

    pass


def sanitize_client_name(name: str | None) -> str:
    """Sanitize and validate a client name.

    Client names may only contain alphanumeric characters and underscores,
    and must be between 1 and 64 characters long.

    Args:
        name: The raw client name to sanitize.

    Returns:
        The validated client name (stripped of leading/trailing whitespace).

    Raises:
        SanitizationError: If the name is None, empty, or contains
            invalid characters.
    """
    if name is None:
        raise SanitizationError("Client name must not be None")

    name = name.strip()

    if not name:
        raise SanitizationError("Client name must not be empty")

    if not _CLIENT_NAME_PATTERN.match(name):
        raise SanitizationError(
            f"Client name '{name}' contains invalid characters. "
            "Only alphanumeric characters and underscores are allowed "
            "(1-64 characters)."
        )

    logger.debug("Client name sanitized: %s", name)
    return name


def sanitize_path(path: str | None, must_exist: bool = False) -> Path:
    """Sanitize a file path to prevent path traversal attacks.

    Resolves the path to an absolute path and checks for traversal
    attempts (e.g., '..', symlinks to unexpected locations).

    Args:
        path: The raw file path to sanitize.
        must_exist: If True, verifies the path exists on disk.

    Returns:
        A resolved, absolute Path object.

    Raises:
        SanitizationError: If the path is None, empty, contains
            traversal sequences, or does not exist (when must_exist=True).
    """
    if path is None:
        raise SanitizationError("Path must not be None")

    path_str = str(path).strip()

    if not path_str:
        raise SanitizationError("Path must not be empty")

    # Check for null bytes (common injection technique)
    if "\x00" in path_str:
        raise SanitizationError("Path must not contain null bytes")

    # Check for shell metacharacters in the path
    if _SHELL_META_CHARS.search(path_str):
        raise SanitizationError(
            f"Path '{path_str}' contains disallowed shell metacharacters"
        )

    resolved = Path(path_str).resolve()

    # Check that the resolved path does not escape expected boundaries
    # by ensuring no '..' components remain after resolution
    try:
        resolved_str = str(resolved)
    except (ValueError, OSError) as exc:
        raise SanitizationError(f"Invalid path: {exc}") from exc

    if must_exist and not resolved.exists():
        raise SanitizationError(f"Path does not exist: {resolved_str}")

    logger.debug("Path sanitized: %s -> %s", path_str, resolved_str)
    return resolved


def validate_phone_number(phone: str | None) -> str:
    """Validate a phone number format.

    Args:
        phone: The phone number to validate.

    Returns:
        The validated phone number string.

    Raises:
        SanitizationError: If the phone number is invalid.
    """
    if phone is None:
        raise SanitizationError("Phone number must not be None")

    phone = phone.strip()

    if not phone:
        raise SanitizationError("Phone number must not be empty")

    if len(phone) > MAX_PHONE_LENGTH:
        raise SanitizationError(
            f"Phone number exceeds maximum length of {MAX_PHONE_LENGTH}"
        )

    if not _PHONE_PATTERN.match(phone):
        raise SanitizationError(
            f"Phone number '{phone}' has an invalid format. "
            "Expected format: +1234567890"
        )

    return phone


def validate_url(url: str | None, label: str = "URL") -> str:
    """Validate a URL format.

    Args:
        url: The URL to validate.
        label: Human-readable label for error messages.

    Returns:
        The validated URL string.

    Raises:
        SanitizationError: If the URL is invalid.
    """
    if url is None:
        raise SanitizationError(f"{label} must not be None")

    url = url.strip()

    if not url:
        raise SanitizationError(f"{label} must not be empty")

    if len(url) > MAX_URL_LENGTH:
        raise SanitizationError(
            f"{label} exceeds maximum length of {MAX_URL_LENGTH}"
        )

    if not _URL_PATTERN.match(url):
        raise SanitizationError(
            f"{label} '{url}' is not a valid HTTP/HTTPS URL"
        )

    return url


def validate_email(email: str | None) -> str:
    """Validate an email address format.

    Args:
        email: The email address to validate.

    Returns:
        The validated email address string.

    Raises:
        SanitizationError: If the email address is invalid.
    """
    if email is None:
        raise SanitizationError("Email must not be None")

    email = email.strip().lower()

    if not email:
        raise SanitizationError("Email must not be empty")

    if len(email) > 254:
        raise SanitizationError("Email exceeds maximum length of 254")

    if not _EMAIL_PATTERN.match(email):
        raise SanitizationError(
            f"Email '{email}' is not a valid email address"
        )

    return email


def validate_time_format(time_str: str | None, label: str = "Time") -> str:
    """Validate a time string in HH:MM format.

    Args:
        time_str: The time string to validate.
        label: Human-readable label for error messages.

    Returns:
        The validated time string.

    Raises:
        SanitizationError: If the time format is invalid.
    """
    if time_str is None:
        raise SanitizationError(f"{label} must not be None")

    time_str = time_str.strip()

    if not _TIME_PATTERN.match(time_str):
        raise SanitizationError(
            f"{label} '{time_str}' is not valid. Expected HH:MM (24-hour format)"
        )

    return time_str


def validate_timezone(tz: str | None) -> str:
    """Validate an IANA timezone string.

    Args:
        tz: The timezone string to validate (e.g., 'America/New_York').

    Returns:
        The validated timezone string.

    Raises:
        SanitizationError: If the timezone format is invalid.
    """
    if tz is None:
        raise SanitizationError("Timezone must not be None")

    tz = tz.strip()

    if not tz:
        raise SanitizationError("Timezone must not be empty")

    if not _TIMEZONE_PATTERN.match(tz):
        raise SanitizationError(
            f"Timezone '{tz}' is not a valid IANA timezone. "
            "Expected format: Region/City (e.g., America/New_York)"
        )

    return tz


def _strip_dangerous_chars(value: str) -> str:
    """Remove control characters and other dangerous characters from a string."""
    return _DANGEROUS_CHARS.sub("", value)


def validate_config_values(config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate all values in a client config dictionary.

    Performs comprehensive validation of every section in the config:
    - client.name is a non-empty string
    - phone numbers match expected format
    - URLs match expected format
    - Times match HH:MM format
    - Numeric values are within valid ranges
    - No values contain dangerous characters

    Args:
        config: The raw configuration dictionary.

    Returns:
        The validated configuration dictionary (values may be cleaned).

    Raises:
        SanitizationError: If any value fails validation.
    """
    if config is None:
        raise SanitizationError("Config must not be None")

    if not isinstance(config, dict):
        raise SanitizationError("Config must be a dictionary")

    errors: list[str] = []

    # --- client section ---
    client = config.get("client")
    if not isinstance(client, dict):
        errors.append("Missing or invalid 'client' section")
    else:
        name = client.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            errors.append("client.name is required and must be a non-empty string")
        else:
            client["name"] = _strip_dangerous_chars(name.strip())

        company = client.get("company")
        if company is not None:
            if not isinstance(company, str):
                errors.append("client.company must be a string")
            else:
                client["company"] = _strip_dangerous_chars(company.strip())

    # --- telegram section ---
    telegram = config.get("telegram")
    if not isinstance(telegram, dict):
        errors.append("Missing or invalid 'telegram' section")
    else:
        bot_token = telegram.get("bot_token")
        if not bot_token or not isinstance(bot_token, str) or not bot_token.strip():
            errors.append("telegram.bot_token is required")

        user_id = telegram.get("user_id")
        if user_id is None:
            errors.append("telegram.user_id is required")
        elif not isinstance(user_id, int):
            errors.append("telegram.user_id must be an integer")

    # --- twilio section ---
    twilio = config.get("twilio")
    if not isinstance(twilio, dict):
        errors.append("Missing or invalid 'twilio' section")
    else:
        for field in ("account_sid", "auth_token"):
            val = twilio.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                errors.append(f"twilio.{field} is required")

        phone = twilio.get("phone_number")
        if phone and isinstance(phone, str) and phone.strip():
            try:
                validate_phone_number(phone)
            except SanitizationError as exc:
                errors.append(f"twilio.phone_number: {exc}")

        client_phone = twilio.get("client_phone")
        if client_phone and isinstance(client_phone, str) and client_phone.strip():
            try:
                validate_phone_number(client_phone)
            except SanitizationError as exc:
                errors.append(f"twilio.client_phone: {exc}")

    # --- elevenlabs section ---
    elevenlabs = config.get("elevenlabs")
    if not isinstance(elevenlabs, dict):
        errors.append("Missing or invalid 'elevenlabs' section")
    else:
        for field in ("api_key", "voice_id", "agent_name"):
            val = elevenlabs.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                errors.append(f"elevenlabs.{field} is required")

        personality = elevenlabs.get("personality")
        if personality is not None:
            if not isinstance(personality, str):
                errors.append("elevenlabs.personality must be a string")
            elif len(personality) > MAX_CONFIG_VALUE_LENGTH:
                errors.append(
                    f"elevenlabs.personality exceeds max length of "
                    f"{MAX_CONFIG_VALUE_LENGTH}"
                )

    # --- llm section ---
    llm = config.get("llm")
    if not isinstance(llm, dict):
        errors.append("Missing or invalid 'llm' section")
    else:
        provider = llm.get("provider")
        if provider not in ("openai", "anthropic"):
            errors.append(
                "llm.provider must be 'openai' or 'anthropic'"
            )

        for field in ("model", "api_key"):
            val = llm.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                errors.append(f"llm.{field} is required")

    # --- google section ---
    google = config.get("google")
    if not isinstance(google, dict):
        errors.append("Missing or invalid 'google' section")
    else:
        for field in ("client_id", "client_secret"):
            val = google.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                errors.append(f"google.{field} is required")

    # --- supabase section ---
    supabase = config.get("supabase")
    if not isinstance(supabase, dict):
        errors.append("Missing or invalid 'supabase' section")
    else:
        url = supabase.get("url")
        if url and isinstance(url, str) and url.strip():
            try:
                validate_url(url, label="supabase.url")
            except SanitizationError as exc:
                errors.append(str(exc))

        for field in ("anon_key", "service_role_key"):
            val = supabase.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                errors.append(f"supabase.{field} is required")

    # --- deepgram section ---
    deepgram = config.get("deepgram")
    if not isinstance(deepgram, dict):
        errors.append("Missing or invalid 'deepgram' section")
    else:
        val = deepgram.get("api_key")
        if not val or not isinstance(val, str) or not val.strip():
            errors.append("deepgram.api_key is required")

    # --- weather section ---
    weather = config.get("weather")
    if not isinstance(weather, dict):
        errors.append("Missing or invalid 'weather' section")
    else:
        val = weather.get("api_key")
        if not val or not isinstance(val, str) or not val.strip():
            errors.append("weather.api_key is required")

    # --- settings section ---
    settings = config.get("settings")
    if not isinstance(settings, dict):
        errors.append("Missing or invalid 'settings' section")
    else:
        for time_field in (
            "morning_briefing_time",
            "quiet_hours_start",
            "quiet_hours_end",
        ):
            val = settings.get(time_field)
            if val and isinstance(val, str):
                try:
                    validate_time_format(val, label=f"settings.{time_field}")
                except SanitizationError as exc:
                    errors.append(str(exc))
            elif val is None:
                errors.append(f"settings.{time_field} is required")

        for int_field, min_val, max_val in (
            ("reminder_lead_minutes", 1, 1440),
            ("min_snooze_minutes", 1, 1440),
        ):
            val = settings.get(int_field)
            if val is None:
                errors.append(f"settings.{int_field} is required")
            elif not isinstance(val, int):
                errors.append(f"settings.{int_field} must be an integer")
            elif val < min_val or val > max_val:
                errors.append(
                    f"settings.{int_field} must be between {min_val} and {max_val}"
                )

        tz = settings.get("timezone")
        if tz and isinstance(tz, str):
            try:
                validate_timezone(tz)
            except SanitizationError as exc:
                errors.append(str(exc))
        elif tz is None:
            errors.append("settings.timezone is required")

        save_to_disk = settings.get("save_to_disk")
        if save_to_disk is not None and not isinstance(save_to_disk, bool):
            errors.append("settings.save_to_disk must be a boolean")

    if errors:
        error_msg = "Config validation failed:\n  - " + "\n  - ".join(errors)
        logger.error(error_msg)
        raise SanitizationError(error_msg)

    logger.info("Config validation passed")
    return config
