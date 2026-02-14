"""APScheduler setup for recurring jobs: briefings, reminders, calendar sync."""

from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import TYPE_CHECKING, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from src.config.loader import AppConfig

logger = logging.getLogger(__name__)

MISFIRE_GRACE_TIME = 300  # 5 minutes


class RafiScheduler:
    """Manages scheduled jobs: morning briefing, reminders, calendar sync."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": MISFIRE_GRACE_TIME,
                "coalesce": True,
                "max_instances": 1,
            }
        )
        self._briefing_callback: Optional[Any] = None
        self._reminder_callback: Optional[Any] = None
        self._calendar_sync_callback: Optional[Any] = None
        self._heartbeat_callback: Optional[Any] = None
        self._heartbeat_interval: int = 30

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def set_briefing_callback(self, callback: Any) -> None:
        """Set the callback function for morning briefings."""
        self._briefing_callback = callback

    def set_reminder_callback(self, callback: Any) -> None:
        """Set the callback function for event reminders."""
        self._reminder_callback = callback

    def set_calendar_sync_callback(self, callback: Any) -> None:
        """Set the callback function for calendar sync."""
        self._calendar_sync_callback = callback

    def add_heartbeat(self, callback: Any, every_minutes: int = 30) -> None:
        """Register the heartbeat job.

        Args:
            callback: Async function to run each tick.
            every_minutes: Interval between heartbeat ticks.
        """
        self._heartbeat_callback = callback
        self._heartbeat_interval = every_minutes

    def setup_jobs(self) -> None:
        """Configure all scheduled jobs based on current settings."""
        self._setup_briefing_job()
        self._setup_reminder_job()
        self._setup_calendar_sync_job()
        self._setup_heartbeat_job()
        logger.info("All scheduled jobs configured")

    def _setup_briefing_job(self) -> None:
        """Schedule the morning briefing call."""
        if not self._briefing_callback:
            logger.warning("No briefing callback set, skipping briefing job")
            return

        briefing_time = self._parse_time(
            self._config.settings.morning_briefing_time
        )
        if not briefing_time:
            logger.error("Invalid briefing time, skipping briefing job")
            return

        self._scheduler.add_job(
            self._briefing_callback,
            trigger=CronTrigger(
                hour=briefing_time.hour,
                minute=briefing_time.minute,
                timezone=self._config.settings.timezone,
            ),
            id="morning_briefing",
            name="Morning Briefing",
            replace_existing=True,
        )
        logger.info(
            "Morning briefing scheduled at %s %s",
            self._config.settings.morning_briefing_time,
            self._config.settings.timezone,
        )

    def _setup_reminder_job(self) -> None:
        """Schedule the reminder check job (runs every minute)."""
        if not self._reminder_callback:
            logger.warning("No reminder callback set, skipping reminder job")
            return

        self._scheduler.add_job(
            self._reminder_callback,
            trigger=IntervalTrigger(minutes=1),
            id="reminder_check",
            name="Reminder Check",
            replace_existing=True,
        )
        logger.info("Reminder check scheduled every 1 minute")

    def _setup_calendar_sync_job(self) -> None:
        """Schedule the calendar sync job (every 15 minutes)."""
        if not self._calendar_sync_callback:
            logger.warning("No calendar sync callback set, skipping sync job")
            return

        self._scheduler.add_job(
            self._calendar_sync_callback,
            trigger=IntervalTrigger(minutes=15),
            id="calendar_sync",
            name="Calendar Sync",
            replace_existing=True,
        )
        logger.info("Calendar sync scheduled every 15 minutes")

    def _setup_heartbeat_job(self) -> None:
        """Schedule the heartbeat check job."""
        if not self._heartbeat_callback:
            logger.info("No heartbeat callback set, skipping heartbeat job")
            return

        self._scheduler.add_job(
            self._heartbeat_callback,
            trigger=IntervalTrigger(minutes=self._heartbeat_interval),
            id="heartbeat",
            name="Heartbeat Check",
            replace_existing=True,
        )
        logger.info(
            "Heartbeat scheduled every %d minutes", self._heartbeat_interval,
        )

    def start(self) -> None:
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    def update_briefing_time(self, new_time: str) -> None:
        """Update the morning briefing time.

        Args:
            new_time: New time in HH:MM format.
        """
        parsed = self._parse_time(new_time)
        if not parsed:
            logger.error("Invalid briefing time: %s", new_time)
            return

        if self._scheduler.get_job("morning_briefing"):
            self._scheduler.reschedule_job(
                "morning_briefing",
                trigger=CronTrigger(
                    hour=parsed.hour,
                    minute=parsed.minute,
                    timezone=self._config.settings.timezone,
                ),
            )
            logger.info("Morning briefing rescheduled to %s", new_time)

    @staticmethod
    def _parse_time(time_str: str) -> Optional[dt_time]:
        """Parse a time string in HH:MM format.

        Args:
            time_str: Time string like "08:00" or "22:30".

        Returns:
            datetime.time object, or None if invalid.
        """
        if not time_str:
            return None
        try:
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                return None
            hour = int(parts[0])
            minute = int(parts[1])
            return dt_time(hour=hour, minute=minute)
        except (ValueError, IndexError):
            return None
