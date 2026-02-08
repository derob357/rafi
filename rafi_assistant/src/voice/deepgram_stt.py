"""Async speech-to-text transcription using Deepgram API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

from src.security.sanitizer import sanitize_text

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0


class DeepgramSTT:
    """Transcribes audio files using the Deepgram API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Deepgram API key is required")
        self._api_key = api_key
        self._base_url = "https://api.deepgram.com/v1/listen"

    async def transcribe_file(self, audio_path: str) -> Optional[str]:
        """Transcribe an audio file and return the text.

        Args:
            audio_path: Path to the audio file (OGG, WAV, MP3, etc.)

        Returns:
            Transcribed text, or None if transcription failed.
        """
        if not audio_path:
            logger.warning("No audio path provided for transcription")
            return None

        path = Path(audio_path)
        if not path.exists():
            logger.error("Audio file not found: %s", audio_path)
            return None

        if path.stat().st_size == 0:
            logger.warning("Audio file is empty: %s", audio_path)
            return None

        content_type = self._get_content_type(path.suffix.lower())

        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._send_request(path, content_type)
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Deepgram API error (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    str(e),
                )
                if attempt < MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                else:
                    return None
            except httpx.RequestError as e:
                logger.error(
                    "Deepgram request error (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    str(e),
                )
                if attempt < MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                else:
                    return None
            except Exception as e:
                logger.exception("Unexpected error during transcription: %s", str(e))
                return None

        return None

    async def _send_request(self, path: Path, content_type: str) -> Optional[str]:
        """Send transcription request to Deepgram."""
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": content_type,
        }
        params = {
            "model": "nova-2",
            "language": "en",
            "smart_format": "true",
            "punctuate": "true",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(path, "rb") as audio_file:
                audio_data = audio_file.read()

            response = await client.post(
                self._base_url,
                headers=headers,
                params=params,
                content=audio_data,
            )
            response.raise_for_status()

        result = response.json()
        transcript = self._extract_transcript(result)

        if transcript:
            transcript = sanitize_text(transcript, max_length=10000)
            logger.info(
                "Transcription successful: %d characters",
                len(transcript),
            )

        return transcript

    @staticmethod
    def _extract_transcript(result: dict) -> Optional[str]:
        """Extract transcript text from Deepgram response."""
        if not result:
            return None

        results = result.get("results")
        if not results:
            return None

        channels = results.get("channels")
        if not channels or len(channels) == 0:
            return None

        alternatives = channels[0].get("alternatives")
        if not alternatives or len(alternatives) == 0:
            return None

        transcript = alternatives[0].get("transcript", "")
        return transcript if transcript.strip() else None

    @staticmethod
    def _get_content_type(extension: str) -> str:
        """Map file extension to MIME content type."""
        content_types = {
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            ".webm": "audio/webm",
        }
        return content_types.get(extension, "audio/ogg")
