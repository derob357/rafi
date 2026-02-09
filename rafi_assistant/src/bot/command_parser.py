"""Parse settings commands from natural language text.

Recognizes commands like "set quiet hours 10pm to 7am",
"set briefing time 8am", "set reminder 15 minutes",
and "set snooze 5 minutes", returning structured updates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SettingsUpdate:
    """Represents a parsed settings update command."""

    key: str
    value: str
    display_message: str


def _parse_time_12h(time_str: str) -> Optional[str]:
    """Convert 12-hour time string to HH:MM 24-hour format.

    Handles formats like '8am', '10pm', '8:30am', '10:00pm', '8 am'.

    Args:
        time_str: Time string in 12-hour format.

    Returns:
        Time in HH:MM format, or None if parsing fails.
    """
    time_str = time_str.strip().lower().replace(" ", "")

    # Match patterns like 8am, 8:30am, 10pm, 10:00pm
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", time_str)
    if not match:
        # Try 24-hour format
        match_24 = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
        if match_24:
            hour = int(match_24.group(1))
            minute = int(match_24.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    period = match.group(3)

    if hour < 1 or hour > 12 or minute < 0 or minute > 59:
        return None

    if period == "am":
        if hour == 12:
            hour = 0
    else:  # pm
        if hour != 12:
            hour += 12

    return f"{hour:02d}:{minute:02d}"


def _parse_minutes(text: str) -> Optional[int]:
    """Extract a minute value from text like '15 minutes', '15 min', '15'.

    Args:
        text: Text containing a minute value.

    Returns:
        Integer minutes, or None if parsing fails.
    """
    match = re.search(r"(\d+)\s*(?:minutes?|mins?|m)?", text.strip())
    if match:
        minutes = int(match.group(1))
        if 1 <= minutes <= 120:
            return minutes
    return None


# Compiled patterns for command recognition
QUIET_HOURS_PATTERN = re.compile(
    r"set\s+quiet\s+hours?\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:to|until|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
    re.IGNORECASE,
)

BRIEFING_TIME_PATTERN = re.compile(
    r"set\s+(?:morning\s+)?briefing\s+(?:time\s+)?(?:to\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
    re.IGNORECASE,
)

REMINDER_PATTERN = re.compile(
    r"set\s+reminder(?:\s+lead)?(?:\s+time)?\s+(?:to\s+)?(\d+)\s*(?:minutes?|mins?|m)?",
    re.IGNORECASE,
)

SNOOZE_PATTERN = re.compile(
    r"set\s+(?:min(?:imum)?\s+)?snooze\s+(?:duration\s+)?(?:to\s+)?(\d+)\s*(?:minutes?|mins?|m)?",
    re.IGNORECASE,
)


def parse_settings_command(text: str) -> Optional[SettingsUpdate]:
    """Parse a settings command from user text input.

    Recognizes the following commands:
    - "set quiet hours 10pm to 7am"
    - "set briefing time 8am"
    - "set reminder 15 minutes"
    - "set snooze 5 minutes"

    Args:
        text: Raw user text input.

    Returns:
        SettingsUpdate if a command is recognized, None otherwise.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Check for quiet hours command
    match = QUIET_HOURS_PATTERN.search(text)
    if match:
        start_str = match.group(1)
        end_str = match.group(2)
        start_time = _parse_time_12h(start_str)
        end_time = _parse_time_12h(end_str)

        if start_time and end_time:
            logger.info("Parsed quiet hours command: %s to %s", start_time, end_time)
            # Return two updates as one — caller should handle both
            # We return the start time and indicate both need updating
            return SettingsUpdate(
                key="quiet_hours",
                value=f"{start_time},{end_time}",
                display_message=f"Quiet hours updated to {start_time} - {end_time}",
            )
        else:
            logger.debug(
                "Failed to parse quiet hours times: start='%s' end='%s'",
                start_str,
                end_str,
            )
            return None

    # Check for briefing time command
    match = BRIEFING_TIME_PATTERN.search(text)
    if match:
        time_str = match.group(1)
        parsed_time = _parse_time_12h(time_str)

        if parsed_time:
            logger.info("Parsed briefing time command: %s", parsed_time)
            return SettingsUpdate(
                key="morning_briefing_time",
                value=parsed_time,
                display_message=f"Morning briefing time updated to {parsed_time}",
            )
        else:
            logger.debug("Failed to parse briefing time: '%s'", time_str)
            return None

    # Check for reminder lead time command
    match = REMINDER_PATTERN.search(text)
    if match:
        minutes_str = match.group(1)
        minutes = _parse_minutes(minutes_str)

        if minutes is not None:
            logger.info("Parsed reminder command: %d minutes", minutes)
            return SettingsUpdate(
                key="reminder_lead_minutes",
                value=str(minutes),
                display_message=f"Reminder lead time updated to {minutes} minutes",
            )
        else:
            logger.debug("Failed to parse reminder minutes: '%s'", minutes_str)
            return None

    # Check for snooze duration command
    match = SNOOZE_PATTERN.search(text)
    if match:
        minutes_str = match.group(1)
        minutes = _parse_minutes(minutes_str)

        if minutes is not None:
            logger.info("Parsed snooze command: %d minutes", minutes)
            return SettingsUpdate(
                key="min_snooze_minutes",
                value=str(minutes),
                display_message=f"Minimum snooze duration updated to {minutes} minutes",
            )
        else:
            logger.debug("Failed to parse snooze minutes: '%s'", minutes_str)
            return None

    return None


async def apply_settings_update(
    update: SettingsUpdate,
    db_client: object,
) -> bool:
    """Apply a parsed settings update to the database.

    Args:
        update: The parsed SettingsUpdate to apply.
        db_client: The SupabaseClient instance.

    Returns:
        True if the update was applied successfully, False otherwise.
    """
    from src.db.supabase_client import SupabaseClient

    if not isinstance(db_client, SupabaseClient):
        logger.error("Invalid db_client type for settings update")
        return False

    db: SupabaseClient = db_client

    try:
        if update.key == "quiet_hours":
            # Split into start and end
            parts = update.value.split(",")
            if len(parts) != 2:
                return False

            await db.upsert(
                "settings",
                {"key": "quiet_hours_start", "value": parts[0]},
                on_conflict="key",
            )
            await db.upsert(
                "settings",
                {"key": "quiet_hours_end", "value": parts[1]},
                on_conflict="key",
            )
        else:
            await db.upsert(
                "settings",
                {"key": update.key, "value": update.value},
                on_conflict="key",
            )

        logger.info("Settings update applied: %s", update.key)
        return True

    except Exception as e:
        logger.error("Failed to apply settings update: %s", e)
        return False
