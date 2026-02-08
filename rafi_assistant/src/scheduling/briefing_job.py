"""Morning briefing job: gathers daily info and calls the client."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.services.calendar_service import CalendarService
    from src.services.email_service import EmailService
    from src.services.task_service import TaskService
    from src.services.weather_service import WeatherService
    from src.voice.twilio_handler import TwilioHandler

logger = logging.getLogger(__name__)


class BriefingJob:
    """Generates and delivers the morning briefing."""

    def __init__(
        self,
        calendar_service: CalendarService,
        email_service: EmailService,
        task_service: TaskService,
        weather_service: WeatherService,
        twilio_handler: TwilioHandler,
        telegram_send_func: Optional[object] = None,
        quiet_hours_start: str = "22:00",
        quiet_hours_end: str = "07:00",
        timezone: str = "America/New_York",
    ) -> None:
        self._calendar = calendar_service
        self._email = email_service
        self._tasks = task_service
        self._weather = weather_service
        self._twilio = twilio_handler
        self._telegram_send = telegram_send_func
        self._quiet_start = quiet_hours_start
        self._quiet_end = quiet_hours_end
        self._timezone = timezone

    async def run(self) -> None:
        """Execute the morning briefing job."""
        logger.info("Starting morning briefing job")

        try:
            briefing_text = await self._build_briefing()

            if self._is_quiet_hours():
                logger.info("Quiet hours active, sending briefing via Telegram")
                await self._send_telegram_briefing(briefing_text)
                return

            call_sid = await self._twilio.initiate_outbound_call(
                context=briefing_text
            )

            if not call_sid:
                logger.warning(
                    "Outbound briefing call failed, falling back to Telegram"
                )
                await self._send_telegram_briefing(briefing_text)
            else:
                logger.info("Morning briefing call initiated: %s", call_sid)

        except Exception as e:
            logger.exception("Morning briefing job failed: %s", str(e))
            try:
                await self._send_telegram_briefing(
                    "I couldn't prepare your full briefing, but I'm still here if you need me!"
                )
            except Exception:
                logger.exception("Failed to send fallback Telegram briefing")

    async def _build_briefing(self) -> str:
        """Build the briefing text from all sources."""
        parts: list[str] = ["Good morning! Here's your daily briefing:\n"]

        # Calendar events
        try:
            events = await self._calendar.list_events(days=1)
            if events:
                parts.append(f"📅 You have {len(events)} event(s) today:")
                for event in events[:5]:
                    summary = event.get("summary", "Untitled event")
                    start = event.get("start_time", "")
                    location = event.get("location", "")
                    line = f"  - {start}: {summary}"
                    if location:
                        line += f" at {location}"
                    parts.append(line)
            else:
                parts.append("📅 No events scheduled for today.")
        except Exception as e:
            logger.error("Failed to fetch calendar for briefing: %s", str(e))
            parts.append("📅 Couldn't fetch your calendar right now.")

        # Weather for next event
        try:
            weather = await self._weather.get_weather_for_next_event()
            if weather:
                parts.append(f"\n🌤️ Weather: {weather}")
        except Exception as e:
            logger.error("Failed to fetch weather for briefing: %s", str(e))

        # Unread emails
        try:
            emails = await self._email.list_emails(unread_only=True)
            if emails:
                parts.append(f"\n📧 You have {len(emails)} unread email(s).")
                for email in emails[:3]:
                    sender = email.get("from", "Unknown")
                    subject = email.get("subject", "No subject")
                    parts.append(f"  - From {sender}: {subject}")
            else:
                parts.append("\n📧 No unread emails.")
        except Exception as e:
            logger.error("Failed to fetch emails for briefing: %s", str(e))
            parts.append("\n📧 Couldn't check your emails right now.")

        # Pending tasks
        try:
            tasks = await self._tasks.list_tasks(status="pending")
            if tasks:
                parts.append(f"\n✅ You have {len(tasks)} pending task(s):")
                for task in tasks[:5]:
                    title = task.get("title", "Untitled")
                    due = task.get("due_date", "")
                    line = f"  - {title}"
                    if due:
                        line += f" (due: {due})"
                    parts.append(line)
            else:
                parts.append("\n✅ No pending tasks.")
        except Exception as e:
            logger.error("Failed to fetch tasks for briefing: %s", str(e))
            parts.append("\n✅ Couldn't check your tasks right now.")

        return "\n".join(parts)

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        try:
            import pytz

            tz = pytz.timezone(self._timezone)
            now = datetime.now(tz).time()

            start_parts = self._quiet_start.split(":")
            end_parts = self._quiet_end.split(":")

            from datetime import time as dt_time

            start = dt_time(int(start_parts[0]), int(start_parts[1]))
            end = dt_time(int(end_parts[0]), int(end_parts[1]))

            if start <= end:
                return start <= now <= end
            else:
                # Wraps midnight (e.g., 22:00 to 07:00)
                return now >= start or now <= end
        except Exception as e:
            logger.error("Error checking quiet hours: %s", str(e))
            return False

    async def _send_telegram_briefing(self, text: str) -> None:
        """Send the briefing as a Telegram message."""
        if self._telegram_send and callable(self._telegram_send):
            try:
                await self._telegram_send(text)  # type: ignore
            except Exception as e:
                logger.error("Failed to send Telegram briefing: %s", str(e))
        else:
            logger.warning("No Telegram send function available for briefing fallback")
