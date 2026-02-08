"""Tests for src/bot/command_parser.py — natural-language settings commands.

Covers:
- "set quiet hours 10pm to 7am" -> correct SettingsUpdate
- "set briefing time 8am" -> correct SettingsUpdate
- "set reminder 15 minutes" -> correct SettingsUpdate
- "set snooze 5 minutes" -> correct SettingsUpdate
- Random text -> None
- Empty string -> None
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

# ---------------------------------------------------------------------------
# Import the command parser.  Stub if not yet written.
# ---------------------------------------------------------------------------
try:
    from src.bot.command_parser import parse_settings_command
except ImportError:
    def parse_settings_command(text: str) -> Optional[Any]:  # type: ignore[misc]
        raise NotImplementedError("src.bot.command_parser.parse_settings_command not yet implemented")

# Attempt to import the SettingsUpdate model if available
try:
    from src.bot.command_parser import SettingsUpdate
except ImportError:
    SettingsUpdate = None  # type: ignore[assignment,misc]


# ===================================================================
# Quiet Hours Commands
# ===================================================================


class TestQuietHoursCommand:
    """Parse quiet-hours setting commands."""

    def test_set_quiet_hours_pm(self):
        result = parse_settings_command("set quiet hours 10pm to 7am")
        assert result is not None
        # Expect quiet_hours_start and quiet_hours_end to be set
        if hasattr(result, "quiet_hours_start"):
            assert result.quiet_hours_start == "22:00"
            assert result.quiet_hours_end == "07:00"
        elif isinstance(result, dict):
            assert result.get("quiet_hours_start") == "22:00"
            assert result.get("quiet_hours_end") == "07:00"

    def test_set_quiet_hours_24h(self):
        result = parse_settings_command("set quiet hours 22:00 to 07:00")
        assert result is not None

    def test_set_quiet_hours_midnight(self):
        result = parse_settings_command("set quiet hours 11pm to 6am")
        assert result is not None
        if hasattr(result, "quiet_hours_start"):
            assert result.quiet_hours_start == "23:00"
            assert result.quiet_hours_end == "06:00"
        elif isinstance(result, dict):
            assert result.get("quiet_hours_start") == "23:00"
            assert result.get("quiet_hours_end") == "06:00"


# ===================================================================
# Briefing Time Commands
# ===================================================================


class TestBriefingTimeCommand:
    """Parse briefing-time setting commands."""

    def test_set_briefing_time_am(self):
        result = parse_settings_command("set briefing time 8am")
        assert result is not None
        if hasattr(result, "morning_briefing_time"):
            assert result.morning_briefing_time == "08:00"
        elif isinstance(result, dict):
            assert result.get("morning_briefing_time") == "08:00"

    def test_set_briefing_time_with_minutes(self):
        result = parse_settings_command("set briefing time 8:30am")
        assert result is not None
        if hasattr(result, "morning_briefing_time"):
            assert result.morning_briefing_time == "08:30"
        elif isinstance(result, dict):
            assert result.get("morning_briefing_time") == "08:30"

    def test_set_morning_briefing(self):
        result = parse_settings_command("set morning briefing 7am")
        assert result is not None

    def test_set_briefing_time_24h(self):
        result = parse_settings_command("set briefing time 08:00")
        assert result is not None


# ===================================================================
# Reminder Lead Time Commands
# ===================================================================


class TestReminderCommand:
    """Parse reminder lead-time setting commands."""

    def test_set_reminder_15(self):
        result = parse_settings_command("set reminder 15 minutes")
        assert result is not None
        if hasattr(result, "reminder_lead_minutes"):
            assert result.reminder_lead_minutes == 15
        elif isinstance(result, dict):
            assert result.get("reminder_lead_minutes") == 15

    def test_set_reminder_30(self):
        result = parse_settings_command("set reminder 30 minutes")
        assert result is not None
        if hasattr(result, "reminder_lead_minutes"):
            assert result.reminder_lead_minutes == 30
        elif isinstance(result, dict):
            assert result.get("reminder_lead_minutes") == 30

    def test_set_reminder_time(self):
        result = parse_settings_command("set reminder time to 10 minutes")
        assert result is not None


# ===================================================================
# Snooze Duration Commands
# ===================================================================


class TestSnoozeCommand:
    """Parse snooze-duration setting commands."""

    def test_set_snooze_5(self):
        result = parse_settings_command("set snooze 5 minutes")
        assert result is not None
        if hasattr(result, "min_snooze_minutes"):
            assert result.min_snooze_minutes == 5
        elif isinstance(result, dict):
            assert result.get("min_snooze_minutes") == 5

    def test_set_snooze_10(self):
        result = parse_settings_command("set snooze 10 minutes")
        assert result is not None
        if hasattr(result, "min_snooze_minutes"):
            assert result.min_snooze_minutes == 10
        elif isinstance(result, dict):
            assert result.get("min_snooze_minutes") == 10

    def test_set_snooze_duration(self):
        result = parse_settings_command("set snooze duration to 15 minutes")
        assert result is not None


# ===================================================================
# Non-Command Text -> None
# ===================================================================


class TestNonCommandText:
    """Random text and empty strings return None."""

    def test_random_text_returns_none(self):
        assert parse_settings_command("What is the weather today?") is None

    def test_greeting_returns_none(self):
        assert parse_settings_command("Hello, how are you?") is None

    def test_calendar_query_returns_none(self):
        assert parse_settings_command("What's on my schedule?") is None

    def test_email_query_returns_none(self):
        assert parse_settings_command("Check my email") is None

    def test_task_creation_returns_none(self):
        assert parse_settings_command("Create a task to buy groceries") is None

    def test_empty_string_returns_none(self):
        assert parse_settings_command("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_settings_command("   ") is None

    def test_none_input(self):
        """None input should return None or raise TypeError."""
        try:
            result = parse_settings_command(None)  # type: ignore[arg-type]
            assert result is None
        except (TypeError, AttributeError):
            pass  # acceptable
