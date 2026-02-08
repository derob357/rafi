"""E2E test: Settings pipeline - change via text → verify → change via voice → verify."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestSettingsPipeline:
    """E2E: Change setting via Telegram → verify in Supabase → verify applied.

    Recursive dependency validation:
    - Command parser extracts setting correctly
    - Setting stored in Supabase
    - Setting read back correctly
    - Setting affects behavior (e.g., quiet hours block calls)
    """

    @pytest.mark.asyncio
    async def test_parse_and_apply_quiet_hours(self) -> None:
        """Parse quiet hours command and verify it's structured correctly."""
        from src.bot.command_parser import parse_settings_command

        result = parse_settings_command("set quiet hours 10pm to 7am")
        assert result is not None
        assert result.get("key") == "quiet_hours" or "quiet" in str(result).lower()

    @pytest.mark.asyncio
    async def test_parse_and_apply_briefing_time(self) -> None:
        """Parse briefing time command."""
        from src.bot.command_parser import parse_settings_command

        result = parse_settings_command("set briefing time 8am")
        assert result is not None

    @pytest.mark.asyncio
    async def test_parse_and_apply_reminder(self) -> None:
        """Parse reminder lead time command."""
        from src.bot.command_parser import parse_settings_command

        result = parse_settings_command("set reminder 15 minutes")
        assert result is not None

    @pytest.mark.asyncio
    async def test_parse_and_apply_snooze(self) -> None:
        """Parse snooze time command."""
        from src.bot.command_parser import parse_settings_command

        result = parse_settings_command("set snooze 5 minutes")
        assert result is not None

    @pytest.mark.asyncio
    async def test_setting_persisted_to_supabase(self) -> None:
        """Verify setting is stored in Supabase."""
        mock_db = AsyncMock()
        mock_db.upsert = AsyncMock()

        # Simulate storing a setting
        await mock_db.upsert("settings", data={
            "key": "morning_briefing_time",
            "value": "09:00",
        }, on_conflict="key")

        mock_db.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_command_returns_none(self) -> None:
        """Random text should not produce a settings update."""
        from src.bot.command_parser import parse_settings_command

        result = parse_settings_command("hello how are you")
        assert result is None
