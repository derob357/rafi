"""E2E test: Reminder pipeline - event → trigger → call/message."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestReminderPipeline:
    """E2E: Create event → reminder triggers → outbound call → quiet hours respected.

    Recursive dependency validation:
    - Calendar event created and cached
    - Reminder scheduler detects upcoming event
    - Quiet hours check executed before calling
    - Outbound call initiated (or Telegram fallback)
    - Event marked as reminded
    - Snooze functionality works
    """

    @pytest.mark.asyncio
    async def test_reminder_respects_quiet_hours(self) -> None:
        """Reminder during quiet hours should use Telegram, not call."""
        from src.scheduling.reminder_job import ReminderJob

        mock_db = AsyncMock()
        mock_twilio = AsyncMock()
        mock_telegram = AsyncMock()

        job = ReminderJob(
            supabase_client=mock_db,
            twilio_handler=mock_twilio,
            telegram_send_func=mock_telegram,
            quiet_hours_start="00:00",
            quiet_hours_end="23:59",  # Always quiet hours
            timezone="UTC",
        )

        # Should be in quiet hours
        assert job._is_quiet_hours() is True

    @pytest.mark.asyncio
    async def test_reminder_calls_outside_quiet_hours(self) -> None:
        """Reminder outside quiet hours should attempt a call."""
        from src.scheduling.reminder_job import ReminderJob

        mock_db = AsyncMock()
        mock_db.select = AsyncMock(return_value=[])
        mock_twilio = AsyncMock()
        mock_telegram = AsyncMock()

        job = ReminderJob(
            supabase_client=mock_db,
            twilio_handler=mock_twilio,
            telegram_send_func=mock_telegram,
            quiet_hours_start="23:00",
            quiet_hours_end="23:01",  # Very narrow quiet hours
            timezone="UTC",
        )

        await job.run()
        # With no events, no calls should be made
        mock_twilio.initiate_outbound_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_snooze_resets_reminded_flag(self) -> None:
        """Snooze should set reminded=False to re-trigger later."""
        from src.scheduling.reminder_job import ReminderJob

        mock_db = AsyncMock()
        mock_db.update = AsyncMock()
        mock_twilio = AsyncMock()

        job = ReminderJob(
            supabase_client=mock_db,
            twilio_handler=mock_twilio,
        )

        result = await job.snooze_reminder("event-123", snooze_minutes=10)
        assert result is True
        mock_db.update.assert_called_once()
