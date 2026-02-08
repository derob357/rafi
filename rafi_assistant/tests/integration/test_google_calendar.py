"""Integration tests for Google Calendar API."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "Google Calendar integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("GOOGLE_TEST_REFRESH_TOKEN"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestGoogleCalendarIntegration:
    """Integration tests against live Google Calendar API."""

    @pytest.fixture(autouse=True)
    def setup_service(self) -> None:
        from src.services.calendar_service import CalendarService
        from src.db.supabase_client import SupabaseClient

        from src.config.loader import SupabaseConfig
        from unittest.mock import MagicMock

        supabase_config = SupabaseConfig(
            url=os.environ.get("TEST_SUPABASE_URL", "https://placeholder.supabase.co"),
            anon_key=os.environ.get("TEST_SUPABASE_ANON_KEY", "placeholder"),
            service_role_key=os.environ.get("TEST_SUPABASE_KEY", "placeholder"),
        )
        db = SupabaseClient(config=supabase_config)
        mock_config = MagicMock()
        mock_config.google.client_id = os.environ.get("GOOGLE_TEST_CLIENT_ID", "")
        mock_config.google.client_secret = os.environ.get("GOOGLE_TEST_CLIENT_SECRET", "")
        mock_config.google.refresh_token = os.environ.get("GOOGLE_TEST_REFRESH_TOKEN", "")
        self.service = CalendarService(config=mock_config, db=db)

    @pytest.mark.asyncio
    async def test_list_events_returns_list(self) -> None:
        events = await self.service.list_events(days=7)
        assert isinstance(events, list)

    @pytest.mark.asyncio
    async def test_create_and_delete_event(self) -> None:
        event = await self.service.create_event(
            summary="Integration Test Event",
            start="2026-12-31T10:00:00",
            end="2026-12-31T11:00:00",
        )
        assert event is not None
        event_id = event.get("id")
        assert event_id is not None

        # Clean up
        result = await self.service.delete_event(event_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_create_modify_delete_event(self) -> None:
        # Create
        event = await self.service.create_event(
            summary="Modify Test Event",
            start="2026-12-31T14:00:00",
            end="2026-12-31T15:00:00",
        )
        assert event is not None
        event_id = event.get("id")

        # Modify
        updated = await self.service.update_event(
            event_id=event_id,
            updates={"summary": "Modified Test Event"},
        )
        assert updated is not None
        assert updated.get("summary") == "Modified Test Event"

        # Delete
        result = await self.service.delete_event(event_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_handles_empty_calendar_gracefully(self) -> None:
        events = await self.service.list_events(days=0)
        assert isinstance(events, list)
