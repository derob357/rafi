"""Unit tests for Twilio handler call/webhook behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.voice.twilio_handler import TwilioHandler


class _DummyRequest:
    def __init__(self, form_data=None):
        self._form_data = form_data or {}

    async def form(self):
        return self._form_data


@pytest.fixture
def twilio_handler():
    with patch("src.voice.twilio_handler.TwilioClient") as mock_client:
        instance = mock_client.return_value
        call = MagicMock()
        call.sid = "CA_test_sid"
        instance.calls.create.return_value = call
        handler = TwilioHandler(
            account_sid="AC1234567890",
            auth_token="auth-token",
            phone_number="+15551234567",
            client_phone="+15557654321",
            webhook_base_url="https://example.com",
        )
        return handler, instance


@pytest.mark.asyncio
async def test_handle_inbound_call_rejects_invalid_signature(twilio_handler):
    handler, _ = twilio_handler
    request = _DummyRequest({"CallSid": "CA1", "From": "+15550000000"})

    with patch("src.voice.twilio_handler.verify_twilio_signature", new=AsyncMock(return_value=False)):
        response = await handler.handle_inbound_call(request)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_handle_inbound_call_without_agent_returns_apology(twilio_handler):
    handler, _ = twilio_handler
    request = _DummyRequest({"CallSid": "CA1", "From": "+15550000000"})

    with patch("src.voice.twilio_handler.verify_twilio_signature", new=AsyncMock(return_value=True)):
        response = await handler.handle_inbound_call(request)

    assert response.status_code == 200
    assert "assistant is not available" in response.body.decode().lower()


@pytest.mark.asyncio
async def test_handle_inbound_call_with_agent_includes_relay(twilio_handler):
    handler, _ = twilio_handler
    handler.set_agent_id("agent_123")
    request = _DummyRequest({"CallSid": "CA1", "From": "+15550000000"})

    with patch("src.voice.twilio_handler.verify_twilio_signature", new=AsyncMock(return_value=True)):
        response = await handler.handle_inbound_call(request)

    body = response.body.decode()
    assert response.status_code == 200
    assert "conversationrelay" in body.lower()
    assert "agent_id=agent_123" in body


@pytest.mark.asyncio
async def test_initiate_outbound_call_without_agent_returns_none(twilio_handler):
    handler, _ = twilio_handler

    result = await handler.initiate_outbound_call(context="test")

    assert result is None


@pytest.mark.asyncio
async def test_initiate_outbound_call_success_returns_sid(twilio_handler):
    handler, client = twilio_handler
    handler.set_agent_id("agent_123")

    result = await handler.initiate_outbound_call(context="briefing")

    assert result == "CA_test_sid"
    client.calls.create.assert_called_once()


@pytest.mark.asyncio
async def test_initiate_outbound_call_handles_exception(twilio_handler):
    handler, client = twilio_handler
    handler.set_agent_id("agent_123")
    client.calls.create.side_effect = RuntimeError("twilio down")

    result = await handler.initiate_outbound_call(context="briefing")

    assert result is None
