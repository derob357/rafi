"""Integration test for Google Calendar using .env credentials.

This test is meant to be kept as a permanent smoke test. It is skipped
unless the required Google credentials are present in the environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

from src.services.calendar_service import CalendarService


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

REQUIRED_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
]

HAS_CREDENTIALS = all(os.environ.get(var) for var in REQUIRED_VARS)
SKIP_REASON = "Google Calendar integration test requires .env credentials"


class _StubDb:
    async def select(self, *args, **kwargs):
        return []

    async def upsert(self, *args, **kwargs):
        return None

    async def delete(self, *args, **kwargs):
        return True


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_google_calendar_env_list_events() -> None:
    """Smoke test: list events using .env refresh token."""
    config = MagicMock()
    config.google.client_id = os.environ.get("GOOGLE_CLIENT_ID")
    config.google.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    service = CalendarService(config=config, db=_StubDb())
    events = await service.list_events(days=1)

    assert isinstance(events, list)
