"""Unit tests for ElevenLabs conversational agent integration logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.voice.elevenlabs_agent import ElevenLabsAgent, extract_transcript_text


def test_constructor_requires_api_key() -> None:
    with pytest.raises(ValueError):
        ElevenLabsAgent(api_key="", voice_id="voice", agent_name="Rafi", personality="Friendly")


def test_constructor_requires_voice_id() -> None:
    with pytest.raises(ValueError):
        ElevenLabsAgent(api_key="key", voice_id="", agent_name="Rafi", personality="Friendly")


@pytest.mark.asyncio
async def test_create_agent_sets_agent_id() -> None:
    agent = ElevenLabsAgent(api_key="key", voice_id="voice", agent_name="Rafi", personality="Friendly")

    with patch("src.voice.elevenlabs_agent.httpx.AsyncClient") as mock_client_cls:
        client = mock_client_cls.return_value.__aenter__.return_value
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"agent_id": "agent_abc"}
        client.post = AsyncMock(return_value=response)

        result = await agent.create_agent(webhook_url="https://example.com")

    assert result == "agent_abc"
    assert agent.agent_id == "agent_abc"


@pytest.mark.asyncio
async def test_create_agent_raises_when_agent_id_missing() -> None:
    agent = ElevenLabsAgent(api_key="key", voice_id="voice", agent_name="Rafi", personality="Friendly")

    with patch("src.voice.elevenlabs_agent.httpx.AsyncClient") as mock_client_cls:
        client = mock_client_cls.return_value.__aenter__.return_value
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {}
        client.post = AsyncMock(return_value=response)

        with pytest.raises(ValueError):
            await agent.create_agent(webhook_url="https://example.com")


@pytest.mark.asyncio
async def test_get_signed_url_returns_none_without_agent_id() -> None:
    agent = ElevenLabsAgent(api_key="key", voice_id="voice", agent_name="Rafi", personality="Friendly")

    result = await agent.get_signed_url()

    assert result is None


@pytest.mark.asyncio
async def test_extract_transcript_text_handles_empty_and_values() -> None:
    assert await extract_transcript_text(None) == ""
    assert await extract_transcript_text({"transcript": []}) == ""

    transcript = await extract_transcript_text(
        {
            "transcript": [
                {"role": "user", "message": "hello"},
                {"role": "assistant", "message": "hi there"},
                {"role": "assistant", "message": ""},
                "invalid",
            ]
        }
    )

    assert "user: hello" in transcript
    assert "assistant: hi there" in transcript
