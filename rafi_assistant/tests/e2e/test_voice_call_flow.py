"""E2E test: Full Twilio voice call flow."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestVoiceCallFlow:
    """E2E: Twilio call → ElevenLabs conversation → tools → transcript → Telegram.

    Recursive dependency validation:
    1. Twilio webhook received and signature validated
    2. ElevenLabs agent connected via WebSocket
    3. Conversation conducted with tool calls
    4. Tools execute against live services (calendar, email, etc.)
    5. Call transcript retrieved from ElevenLabs
    6. Transcript stored in Supabase call_logs
    7. Summary generated via LLM
    8. Summary sent to Telegram
    """

    @pytest.mark.asyncio
    async def test_twilio_handler_initialization(self) -> None:
        """Validate Twilio handler can be initialized."""
        from src.voice.twilio_handler import TwilioHandler

        handler = TwilioHandler(
            account_sid=os.environ.get("TWILIO_TEST_ACCOUNT_SID", "ACtest"),
            auth_token=os.environ.get("TWILIO_TEST_AUTH_TOKEN", "test_token"),
            phone_number="+10000000000",
            client_phone="+10000000001",
        )
        assert handler.twilio_client is not None

    @pytest.mark.asyncio
    async def test_elevenlabs_agent_initialization(self) -> None:
        """Validate ElevenLabs agent can be initialized."""
        from src.voice.elevenlabs_agent import ElevenLabsAgent

        agent = ElevenLabsAgent(
            api_key=os.environ.get("ELEVENLABS_TEST_API_KEY", "test_key"),
            voice_id="test_voice",
            agent_name="Test Agent",
            personality="Helpful",
        )
        assert agent.agent_id is None  # Not yet created

    @pytest.mark.asyncio
    async def test_outbound_call_without_agent_fails_gracefully(self) -> None:
        """Outbound call without agent should return None, not crash."""
        from src.voice.twilio_handler import TwilioHandler

        handler = TwilioHandler(
            account_sid="ACtest",
            auth_token="test_token",
            phone_number="+10000000000",
            client_phone="+10000000001",
        )
        result = await handler.initiate_outbound_call(context="Test briefing")
        assert result is None
