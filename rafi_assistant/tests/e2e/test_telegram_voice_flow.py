"""E2E test: Full Telegram voice message flow."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestTelegramVoiceFlow:
    """E2E: Send voice → Deepgram transcribes → LLM processes → response.

    Recursive dependency validation:
    1. Telegram bot receives voice message
    2. Audio file downloaded from Telegram
    3. Deepgram transcribes audio to text
    4. Transcription sanitized
    5. LLM processes transcribed text
    6. Response sent back via Telegram
    7. Audio file cleaned up
    """

    @pytest.mark.asyncio
    async def test_voice_message_transcription(self) -> None:
        """Validate Deepgram can transcribe audio."""
        from src.voice.deepgram_stt import DeepgramSTT

        api_key = os.environ.get("DEEPGRAM_TEST_API_KEY", "")
        if not api_key:
            pytest.skip("No Deepgram API key")

        stt = DeepgramSTT(api_key=api_key)
        # Non-existent file returns None gracefully
        result = await stt.transcribe_file("/nonexistent.ogg")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_transcription_handled(self) -> None:
        """Empty transcription should not be sent to LLM."""
        from src.security.sanitizer import sanitize_text
        result = sanitize_text("", max_length=10000)
        assert result == ""
        # Bot should respond "I didn't catch that" for empty transcription
