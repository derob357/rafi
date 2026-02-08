"""E2E test: Email send → verify in sent folder."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestEmailRoundtrip:
    """E2E: Send email → verify appears in Gmail sent folder.

    Recursive dependency validation:
    - Gmail API connectivity
    - OAuth tokens valid
    - Email composed correctly
    - Email sent successfully
    - Email found in sent folder
    """

    @pytest.fixture(autouse=True)
    def setup_service(self) -> None:
        from src.services.email_service import EmailService

        from unittest.mock import MagicMock

        mock_config = MagicMock()
        mock_config.google.client_id = os.environ.get("GOOGLE_TEST_CLIENT_ID", "")
        mock_config.google.client_secret = os.environ.get("GOOGLE_TEST_CLIENT_SECRET", "")
        mock_config.google.refresh_token = os.environ.get("GOOGLE_TEST_REFRESH_TOKEN", "")
        self.service = EmailService(config=mock_config, db=MagicMock())
        self.test_email = os.environ.get("GMAIL_TEST_ADDRESS", "")

    @pytest.mark.asyncio
    async def test_send_and_verify_email(self) -> None:
        """Send email and verify it appears in sent folder."""
        if not self.test_email:
            pytest.skip("No test email address configured")

        import uuid
        unique_subject = f"E2E Test {uuid.uuid4().hex[:8]}"

        # Step 1: Send email
        result = await self.service.send_email(
            to=self.test_email,
            subject=unique_subject,
            body="This is an automated E2E test email. Please ignore.",
        )
        assert result is True, "Failed to send email"

        # Step 2: Search sent folder for the email
        import asyncio
        await asyncio.sleep(3)  # Wait for email to appear

        results = await self.service.search_emails(f"subject:{unique_subject}")
        assert len(results) > 0, f"Sent email not found with subject: {unique_subject}"
