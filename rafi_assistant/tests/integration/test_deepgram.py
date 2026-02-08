"""Integration tests for Deepgram speech-to-text."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "Deepgram integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("DEEPGRAM_TEST_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestDeepgramIntegration:
    """Integration tests against live Deepgram API."""

    @pytest.fixture(autouse=True)
    def setup_stt(self) -> None:
        from src.voice.deepgram_stt import DeepgramSTT

        self.stt = DeepgramSTT(
            api_key=os.environ.get("DEEPGRAM_TEST_API_KEY", ""),
        )

    @pytest.mark.asyncio
    async def test_transcribe_nonexistent_file(self) -> None:
        result = await self.stt.transcribe_file("/nonexistent/audio.ogg")
        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_empty_path(self) -> None:
        result = await self.stt.transcribe_file("")
        assert result is None
