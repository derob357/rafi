"""Heartbeat runner — proactive autonomous check loop.

Runs on an APScheduler interval (default: every 30 minutes). Each tick:
1. Reads HEARTBEAT.md for the checklist
2. Checks quiet hours — skips if outside active window
3. Gathers data from integrations (email, calendar, tasks, weather)
4. Sends gathered context to LLM
5. LLM decides what needs attention
6. If HEARTBEAT_OK → log and skip notification
7. If alert content → deliver via preferred channel
8. Deduplicates: same alert not sent within 24h
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from src.channels.manager import ChannelManager
from src.config.loader import AppConfig
from src.llm.provider import LLMProvider
from src.services.calendar_service import CalendarService
from src.services.email_service import EmailService
from src.services.memory_files import MemoryFileService
from src.services.task_service import TaskService
from src.services.weather_service import WeatherService

logger = logging.getLogger(__name__)

HEARTBEAT_OK = "HEARTBEAT_OK"


class HeartbeatRunner:
    """Proactive heartbeat that checks services and notifies the user."""

    def __init__(
        self,
        config: AppConfig,
        llm: LLMProvider,
        memory_files: MemoryFileService,
        channel_manager: ChannelManager,
        calendar: CalendarService,
        email: EmailService,
        tasks: TaskService,
        weather: WeatherService,
    ) -> None:
        self._config = config
        self._llm = llm
        self._memory_files = memory_files
        self._channels = channel_manager
        self._calendar = calendar
        self._email = email
        self._tasks = tasks
        self._weather = weather
        # Dedup: maps alert summary → last sent timestamp
        self._sent_alerts: dict[str, datetime] = {}

    def _is_quiet_hours(self) -> bool:
        """Check if we're currently in quiet hours."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(self._config.settings.timezone)
            now = datetime.now(tz)
            quiet_start = self._parse_hour(self._config.settings.quiet_hours_start)
            quiet_end = self._parse_hour(self._config.settings.quiet_hours_end)

            if quiet_start is None or quiet_end is None:
                return False

            current_hour = now.hour + now.minute / 60.0

            # Handle overnight quiet hours (e.g. 22:00 - 07:00)
            if quiet_start > quiet_end:
                return current_hour >= quiet_start or current_hour < quiet_end
            return quiet_start <= current_hour < quiet_end
        except Exception:
            return False

    @staticmethod
    def _parse_hour(time_str: str) -> Optional[float]:
        try:
            parts = time_str.strip().split(":")
            return int(parts[0]) + int(parts[1]) / 60.0
        except (ValueError, IndexError):
            return None

    async def run(self) -> None:
        """Execute one heartbeat tick. Called by APScheduler."""
        # Skip if HEARTBEAT.md is empty/has no actionable content
        if self._memory_files.is_heartbeat_empty():
            logger.debug("Heartbeat checklist empty, skipping")
            return

        # Skip during quiet hours
        if self._is_quiet_hours():
            logger.debug("Quiet hours active, skipping heartbeat")
            return

        logger.info("Heartbeat tick starting")

        # Gather service data
        context = await self._gather_context()

        # Build LLM prompt
        heartbeat_md = self._memory_files.load_heartbeat()
        prompt = self._build_prompt(heartbeat_md, context)

        # Ask LLM to evaluate
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Run the heartbeat check now."},
                ],
            )
            content = response.get("content", HEARTBEAT_OK)
        except Exception as e:
            logger.error("Heartbeat LLM error: %s", e)
            return

        # Check for HEARTBEAT_OK
        if HEARTBEAT_OK in content:
            logger.info("Heartbeat: all clear")
            return

        # Dedup check
        alert_key = content[:100]  # first 100 chars as dedup key
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (datetime.utcnow() - last_sent) < timedelta(hours=24):
            logger.info("Heartbeat: suppressing duplicate alert")
            return

        # Deliver notification
        max_chars = 300
        notification = content[:max_chars]
        result = await self._channels.send_to_preferred(notification)
        logger.info("Heartbeat notification sent: %s", result)

        # Record for dedup
        self._sent_alerts[alert_key] = datetime.utcnow()

        # Clean old dedup entries
        cutoff = datetime.utcnow() - timedelta(hours=48)
        self._sent_alerts = {
            k: v for k, v in self._sent_alerts.items() if v > cutoff
        }

    async def _gather_context(self) -> dict[str, str]:
        """Gather data from all integrations for the heartbeat check."""
        context: dict[str, str] = {}

        # Unread emails
        try:
            emails = await self._email.list_emails(count=10, unread_only=True)
            if emails:
                lines = [
                    f"- From: {e.get('from', '?')} | Subject: {e.get('subject', '?')}"
                    for e in emails[:5]
                ]
                context["unread_emails"] = f"{len(emails)} unread:\n" + "\n".join(lines)
            else:
                context["unread_emails"] = "No unread emails."
        except Exception as e:
            context["unread_emails"] = f"Email check failed: {e}"

        # Upcoming events (next 2 hours)
        try:
            events = await self._calendar.list_events(days=1)
            if events:
                lines = [
                    f"- {e.get('summary', '?')} at {e.get('start', '?')}"
                    for e in events[:5]
                ]
                context["upcoming_events"] = "\n".join(lines)
            else:
                context["upcoming_events"] = "No upcoming events today."
        except Exception as e:
            context["upcoming_events"] = f"Calendar check failed: {e}"

        # Pending tasks
        try:
            tasks = await self._tasks.list_tasks(status="pending")
            if tasks:
                lines = [
                    f"- {t.get('title', '?')}"
                    + (f" (due: {t['due_date']})" if t.get("due_date") else "")
                    for t in tasks[:5]
                ]
                context["pending_tasks"] = f"{len(tasks)} pending:\n" + "\n".join(lines)
            else:
                context["pending_tasks"] = "No pending tasks."
        except Exception as e:
            context["pending_tasks"] = f"Task check failed: {e}"

        # Weather
        try:
            weather = await self._weather.get_weather(
                self._config.settings.timezone.split("/")[-1]
            )
            context["weather"] = weather if isinstance(weather, str) else str(weather)
        except Exception:
            context["weather"] = "Weather check unavailable."

        return context

    def _build_prompt(self, heartbeat_md: str, context: dict[str, str]) -> str:
        """Build the LLM prompt for heartbeat evaluation."""
        context_text = "\n\n".join(
            f"### {key.replace('_', ' ').title()}\n{value}"
            for key, value in context.items()
        )

        return (
            f"You are a proactive assistant running a periodic heartbeat check.\n\n"
            f"## Checklist\n{heartbeat_md}\n\n"
            f"## Current Data\n{context_text}\n\n"
            f"## Instructions\n"
            f"Review the data against the checklist. If anything needs the user's "
            f"attention, write a concise alert message (max 300 characters). "
            f"If everything is fine, respond with exactly: {HEARTBEAT_OK}\n"
            f"Do NOT include {HEARTBEAT_OK} if there is something to report."
        )
