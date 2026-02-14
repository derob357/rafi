"""Unit tests for scheduler job setup and time parsing."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.scheduling.scheduler import RafiScheduler


def _make_scheduler(mock_config):
    scheduler = RafiScheduler(mock_config)
    scheduler._scheduler = MagicMock()
    scheduler._scheduler.running = False
    return scheduler


def test_parse_time_valid_values() -> None:
    parsed = RafiScheduler._parse_time("08:30")
    assert parsed is not None
    assert parsed.hour == 8
    assert parsed.minute == 30


def test_parse_time_invalid_values() -> None:
    assert RafiScheduler._parse_time("") is None
    assert RafiScheduler._parse_time("830") is None
    assert RafiScheduler._parse_time("bad") is None


def test_setup_briefing_job_skips_without_callback(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)

    scheduler._setup_briefing_job()

    scheduler._scheduler.add_job.assert_not_called()


def test_setup_briefing_job_adds_job_with_callback(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)
    callback = MagicMock()
    scheduler.set_briefing_callback(callback)

    scheduler._setup_briefing_job()

    scheduler._scheduler.add_job.assert_called_once()
    kwargs = scheduler._scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "morning_briefing"


def test_setup_reminder_job_skips_without_callback(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)

    scheduler._setup_reminder_job()

    scheduler._scheduler.add_job.assert_not_called()


def test_setup_reminder_job_adds_job(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)
    callback = MagicMock()
    scheduler.set_reminder_callback(callback)

    scheduler._setup_reminder_job()

    scheduler._scheduler.add_job.assert_called_once()
    kwargs = scheduler._scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "reminder_check"


def test_setup_calendar_sync_job_adds_job(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)
    callback = MagicMock()
    scheduler.set_calendar_sync_callback(callback)

    scheduler._setup_calendar_sync_job()

    scheduler._scheduler.add_job.assert_called_once()
    kwargs = scheduler._scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "calendar_sync"


def test_setup_heartbeat_job_adds_job(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)
    callback = MagicMock()
    scheduler.add_heartbeat(callback, every_minutes=12)

    scheduler._setup_heartbeat_job()

    scheduler._scheduler.add_job.assert_called_once()
    kwargs = scheduler._scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "heartbeat"


def test_update_briefing_time_reschedules_existing_job(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)
    scheduler._scheduler.get_job.return_value = object()

    scheduler.update_briefing_time("09:45")

    scheduler._scheduler.reschedule_job.assert_called_once()


def test_update_briefing_time_invalid_time_no_reschedule(mock_config) -> None:
    scheduler = _make_scheduler(mock_config)

    scheduler.update_briefing_time("bad")

    scheduler._scheduler.reschedule_job.assert_not_called()
