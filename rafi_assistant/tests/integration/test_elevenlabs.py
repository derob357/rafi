"""Integration tests for ElevenLabs Conversational AI."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "ElevenLabs integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("ELEVENLABS_TEST_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestElevenLabsIntegration:
    """Integration tests against live ElevenLabs API."""

    @pytest.fixture(autouse=True)
    def setup_agent(self) -> None:
        from src.voice.elevenlabs_agent import ElevenLabsAgent

        self.agent = ElevenLabsAgent(
            api_key=os.environ.get("ELEVENLABS_TEST_API_KEY", ""),
            voice_id=os.environ.get("ELEVENLABS_TEST_VOICE_ID", ""),
            agent_name="Test Agent",
            personality="Helpful and concise",
        )

    @pytest.mark.asyncio
    async def test_create_agent(self) -> None:
        agent_id = await self.agent.create_agent(
            webhook_url="https://example.com",
        )
        assert agent_id is not None
        assert len(agent_id) > 0

    @pytest.mark.asyncio
    async def test_get_signed_url_after_create(self) -> None:
        await self.agent.create_agent(webhook_url="https://example.com")
        url = await self.agent.get_signed_url()
        assert url is not None
        assert url.startswith("wss://")
