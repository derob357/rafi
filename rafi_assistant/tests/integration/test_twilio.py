"""Integration tests for Twilio API."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "Twilio integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("TWILIO_TEST_ACCOUNT_SID"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestTwilioIntegration:
    """Integration tests against live Twilio API."""

    @pytest.fixture(autouse=True)
    def setup_handler(self) -> None:
        from src.voice.twilio_handler import TwilioHandler

        self.handler = TwilioHandler(
            account_sid=os.environ.get("TWILIO_TEST_ACCOUNT_SID", ""),
            auth_token=os.environ.get("TWILIO_TEST_AUTH_TOKEN", ""),
            phone_number=os.environ.get("TWILIO_TEST_PHONE_NUMBER", ""),
            client_phone=os.environ.get("TWILIO_TEST_CLIENT_PHONE", ""),
        )

    def test_twilio_client_initialized(self) -> None:
        assert self.handler.twilio_client is not None

    @pytest.mark.asyncio
    async def test_outbound_call_without_agent_returns_none(self) -> None:
        """Outbound call without agent ID should return None."""
        result = await self.handler.initiate_outbound_call()
        assert result is None
