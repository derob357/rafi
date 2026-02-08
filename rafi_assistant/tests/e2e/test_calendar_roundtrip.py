"""E2E test: Calendar create → read → modify → delete round-trip."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestCalendarRoundtrip:
    """E2E: Create event → verify → modify → verify → cancel → verify.

    Recursive dependency validation at each step:
    - Google API connectivity
    - OAuth tokens valid
    - Event data persisted correctly
    - Modification applied
    - Deletion confirmed
    """

    @pytest.fixture(autouse=True)
    def setup_service(self) -> None:
        from src.services.calendar_service import CalendarService
        from src.db.supabase_client import SupabaseClient

        from src.config.loader import AppConfig, SupabaseConfig

        supabase_config = SupabaseConfig(
            url=os.environ.get("TEST_SUPABASE_URL", "https://placeholder.supabase.co"),
            anon_key=os.environ.get("TEST_SUPABASE_ANON_KEY", "placeholder"),
            service_role_key=os.environ.get("TEST_SUPABASE_KEY", "placeholder"),
        )
        db = SupabaseClient(config=supabase_config)
        # Build minimal config for CalendarService
        from unittest.mock import MagicMock
        mock_config = MagicMock(spec=AppConfig)
        mock_config.google.client_id = os.environ.get("GOOGLE_TEST_CLIENT_ID", "")
        mock_config.google.client_secret = os.environ.get("GOOGLE_TEST_CLIENT_SECRET", "")
        mock_config.google.refresh_token = os.environ.get("GOOGLE_TEST_REFRESH_TOKEN", "")
        self.service = CalendarService(config=mock_config, db=db)

    @pytest.mark.asyncio
    async def test_full_calendar_roundtrip(self) -> None:
        """Create → read → modify → verify → delete → verify."""
        # Step 1: Create event
        event = await self.service.create_event(
            summary="E2E Roundtrip Test",
            start="2026-12-31T09:00:00",
            end="2026-12-31T10:00:00",
            location="Test Location",
        )
        assert event is not None, "Failed to create event"
        event_id = event.get("id")
        assert event_id is not None, "Event missing ID"

        # Step 2: Read and verify
        events = await self.service.list_events(days=365)
        found = any(e.get("google_event_id") == event_id for e in events)
        assert found, "Created event not found in listing"

        # Step 3: Modify
        updated = await self.service.update_event(
            event_id=event_id,
            updates={"summary": "E2E Modified Test"},
        )
        assert updated is not None, "Failed to modify event"
        assert updated.get("summary") == "E2E Modified Test"

        # Step 4: Verify modification
        events = await self.service.list_events(days=365)
        modified = [e for e in events if e.get("google_event_id") == event_id]
        assert len(modified) == 1
        assert modified[0].get("summary") == "E2E Modified Test"

        # Step 5: Delete
        result = await self.service.delete_event(event_id)
        assert result is True, "Failed to delete event"

        # Step 6: Verify deletion
        events = await self.service.list_events(days=365)
        still_exists = any(e.get("google_event_id") == event_id for e in events)
        assert not still_exists, "Event still exists after deletion"
