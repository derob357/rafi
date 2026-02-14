"""Unit tests for heartbeat runner decisions and dedup flow."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.scheduling.heartbeat import HEARTBEAT_OK, HeartbeatRunner


@pytest.fixture
def heartbeat_runner(mock_config):
    llm = MagicMock()
    llm.chat = AsyncMock(return_value={"content": HEARTBEAT_OK})

    memory_files = MagicMock()
    memory_files.is_heartbeat_empty.return_value = False
    memory_files.load_heartbeat.return_value = "checklist"

    channels = MagicMock()
    channels.send_to_preferred = AsyncMock(return_value={"status": "sent"})

    calendar = MagicMock()
    calendar.list_events = AsyncMock(return_value=[])

    email = MagicMock()
    email.list_emails = AsyncMock(return_value=[])

    tasks = MagicMock()
    tasks.list_tasks = AsyncMock(return_value=[])

    weather = MagicMock()
    weather.get_weather = AsyncMock(return_value="Sunny")

    runner = HeartbeatRunner(
        config=mock_config,
        llm=llm,
        memory_files=memory_files,
        channel_manager=channels,
        calendar=calendar,
        email=email,
        tasks=tasks,
        weather=weather,
    )
    return runner


def test_parse_hour() -> None:
    assert HeartbeatRunner._parse_hour("22:30") == 22.5
    assert HeartbeatRunner._parse_hour("invalid") is None


@pytest.mark.asyncio
async def test_run_skips_when_checklist_empty(heartbeat_runner) -> None:
    heartbeat_runner._memory_files.is_heartbeat_empty.return_value = True

    await heartbeat_runner.run()

    heartbeat_runner._llm.chat.assert_not_called()
    heartbeat_runner._channels.send_to_preferred.assert_not_called()


@pytest.mark.asyncio
async def test_run_skips_during_quiet_hours(heartbeat_runner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heartbeat_runner, "_is_quiet_hours", lambda: True)

    await heartbeat_runner.run()

    heartbeat_runner._llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_run_no_alert_when_heartbeat_ok(heartbeat_runner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heartbeat_runner, "_is_quiet_hours", lambda: False)
    heartbeat_runner._llm.chat = AsyncMock(return_value={"content": HEARTBEAT_OK})

    await heartbeat_runner.run()

    heartbeat_runner._channels.send_to_preferred.assert_not_called()


@pytest.mark.asyncio
async def test_run_sends_alert(heartbeat_runner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heartbeat_runner, "_is_quiet_hours", lambda: False)
    heartbeat_runner._llm.chat = AsyncMock(return_value={"content": "You have an urgent task due soon."})

    await heartbeat_runner.run()

    heartbeat_runner._channels.send_to_preferred.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_dedup_suppresses_duplicate_within_24h(heartbeat_runner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heartbeat_runner, "_is_quiet_hours", lambda: False)
    alert = "Action needed: meeting starts in 20 minutes"
    heartbeat_runner._llm.chat = AsyncMock(return_value={"content": alert})

    await heartbeat_runner.run()
    await heartbeat_runner.run()

    assert heartbeat_runner._channels.send_to_preferred.await_count == 1


@pytest.mark.asyncio
async def test_gather_context_handles_partial_failures(heartbeat_runner) -> None:
    heartbeat_runner._email.list_emails = AsyncMock(side_effect=RuntimeError("email down"))
    heartbeat_runner._calendar.list_events = AsyncMock(return_value=[{"summary": "Standup", "start": "09:00"}])
    heartbeat_runner._tasks.list_tasks = AsyncMock(return_value=[{"title": "Review", "due_date": "today"}])
    heartbeat_runner._weather.get_weather = AsyncMock(side_effect=RuntimeError("weather down"))

    context = await heartbeat_runner._gather_context()

    assert "Email check failed" in context["unread_emails"]
    assert "Standup" in context["upcoming_events"]
    assert "Review" in context["pending_tasks"]
    assert context["weather"] == "Weather check unavailable."


def test_build_prompt_contains_sections(heartbeat_runner) -> None:
    context = {"pending_tasks": "1 pending", "weather": "Sunny"}

    prompt = heartbeat_runner._build_prompt("- check", context)

    assert "## Checklist" in prompt
    assert "## Current Data" in prompt
    assert "HEARTBEAT_OK" in prompt
