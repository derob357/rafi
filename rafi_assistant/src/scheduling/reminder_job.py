"""Event reminder job: checks for upcoming events and sends reminders."""

from __future__ import annotations

import logging
from datetime import datetime, time as dt_time, timedelta
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.db.supabase_client import SupabaseClient
    from src.voice.twilio_handler import TwilioHandler

logger = logging.getLogger(__name__)


class ReminderJob:
    """Checks upcoming events and triggers reminder calls or messages."""

    def __init__(
        self,
        supabase_client: SupabaseClient,
        twilio_handler: TwilioHandler,
        telegram_send_func: Optional[object] = None,
        reminder_lead_minutes: int = 15,
        min_snooze_minutes: int = 5,
        quiet_hours_start: str = "22:00",
        quiet_hours_end: str = "07:00",
        timezone: str = "America/New_York",
    ) -> None:
        self._db = supabase_client
        self._twilio = twilio_handler
        self._telegram_send = telegram_send_func
        self._lead_minutes = reminder_lead_minutes
        self._snooze_minutes = min_snooze_minutes
        self._quiet_start = quiet_hours_start
        self._quiet_end = quiet_hours_end
        self._timezone = timezone

    async def run(self) -> None:
        """Check for upcoming events and send reminders."""
        try:
            events = await self._get_upcoming_events()
            if not events:
                return

            for event in events:
                await self._process_event_reminder(event)

        except Exception as e:
            logger.exception("Reminder job failed: %s", str(e))

    async def _get_upcoming_events(self) -> list[dict[str, Any]]:
        """Get events that need reminders from the cache."""
        try:
            now = datetime.utcnow()
            window_end = now + timedelta(minutes=self._lead_minutes)

            result = await self._db.select(
                "events_cache",
                filters={
                    "reminded": False,
                    "start_time__gte": now.isoformat(),
                    "start_time__lte": window_end.isoformat(),
                },
            )
            return result if result else []

        except Exception as e:
            logger.error("Failed to fetch upcoming events: %s", str(e))
            return []

    async def _process_event_reminder(self, event: dict[str, Any]) -> None:
        """Process a single event reminder."""
        event_id = event.get("id")
        summary = event.get("summary", "Untitled event")
        start_time = event.get("start_time", "")
        location = event.get("location", "")

        if not event_id:
            logger.warning("Event missing ID, skipping reminder")
            return

        reminder_text = f"Reminder: {summary}"
        if start_time:
            reminder_text += f" starts at {start_time}"
        if location:
            reminder_text += f" at {location}"

        logger.info("Processing reminder for event: %s", summary)

        # Check quiet hours before calling
        if self._is_quiet_hours():
            logger.info("Quiet hours active, sending reminder via Telegram")
            await self._send_telegram_reminder(reminder_text)
            await self._mark_reminded(event_id)
            return

        # Try to call
        call_sid = await self._twilio.initiate_outbound_call(
            context=reminder_text
        )

        if call_sid:
            logger.info("Reminder call initiated for '%s': %s", summary, call_sid)
            await self._mark_reminded(event_id)
        else:
            # Retry once after a short delay
            import asyncio
            await asyncio.sleep(120)  # 2 minutes

            call_sid = await self._twilio.initiate_outbound_call(
                context=reminder_text
            )

            if call_sid:
                logger.info("Reminder call succeeded on retry for '%s'", summary)
                await self._mark_reminded(event_id)
            else:
                logger.warning(
                    "Reminder call failed for '%s', falling back to Telegram",
                    summary,
                )
                await self._send_telegram_reminder(reminder_text)
                await self._mark_reminded(event_id)

    async def _mark_reminded(self, event_id: str) -> None:
        """Mark an event as reminded in the cache."""
        try:
            await self._db.update(
                "events_cache",
                record_id=event_id,
                data={"reminded": True},
            )
        except Exception as e:
            logger.error("Failed to mark event %s as reminded: %s", event_id, str(e))

    async def snooze_reminder(self, event_id: str, snooze_minutes: Optional[int] = None) -> bool:
        """Snooze a reminder for the specified duration.

        Args:
            event_id: The event cache ID.
            snooze_minutes: Minutes to snooze. Uses min_snooze_minutes if less.

        Returns:
            True if snooze was applied.
        """
        if not event_id:
            return False

        minutes = max(
            snooze_minutes or self._snooze_minutes,
            self._snooze_minutes,
        )

        try:
            await self._db.update(
                "events_cache",
                record_id=event_id,
                data={"reminded": False},
            )
            logger.info("Snoozed reminder for event %s for %d minutes", event_id, minutes)
            return True
        except Exception as e:
            logger.error("Failed to snooze reminder for %s: %s", event_id, str(e))
            return False

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        try:
            import pytz

            tz = pytz.timezone(self._timezone)
            now = datetime.now(tz).time()

            start_parts = self._quiet_start.split(":")
            end_parts = self._quiet_end.split(":")

            start = dt_time(int(start_parts[0]), int(start_parts[1]))
            end = dt_time(int(end_parts[0]), int(end_parts[1]))

            if start <= end:
                return start <= now <= end
            else:
                return now >= start or now <= end
        except Exception as e:
            logger.error("Error checking quiet hours: %s", str(e))
            return False

    async def _send_telegram_reminder(self, text: str) -> None:
        """Send a reminder via Telegram."""
        if self._telegram_send and callable(self._telegram_send):
            try:
                await self._telegram_send(text)  # type: ignore
            except Exception as e:
                logger.error("Failed to send Telegram reminder: %s", str(e))
        else:
            logger.warning("No Telegram send function for reminder fallback")
