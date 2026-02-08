"""Integration tests for Gmail API."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "Gmail integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("GOOGLE_TEST_REFRESH_TOKEN"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestGmailIntegration:
    """Integration tests against live Gmail API."""

    @pytest.fixture(autouse=True)
    def setup_service(self) -> None:
        from src.services.email_service import EmailService

        from src.db.supabase_client import SupabaseClient
        from unittest.mock import MagicMock

        mock_config = MagicMock()
        mock_config.google.client_id = os.environ.get("GOOGLE_TEST_CLIENT_ID", "")
        mock_config.google.client_secret = os.environ.get("GOOGLE_TEST_CLIENT_SECRET", "")
        mock_config.google.refresh_token = os.environ.get("GOOGLE_TEST_REFRESH_TOKEN", "")
        self.service = EmailService(config=mock_config, db=MagicMock())

    @pytest.mark.asyncio
    async def test_list_emails_returns_list(self) -> None:
        emails = await self.service.list_emails(count=5)
        assert isinstance(emails, list)

    @pytest.mark.asyncio
    async def test_search_emails(self) -> None:
        results = await self.service.search_emails("subject:test")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_list_unread_emails(self) -> None:
        emails = await self.service.list_emails(unread_only=True)
        assert isinstance(emails, list)
