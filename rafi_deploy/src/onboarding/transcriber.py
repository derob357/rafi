"""Transcribe audio files using the Deepgram API.

Sends audio files to Deepgram's speech-to-text service and returns
the transcript text. Supports large files and includes automatic
retry logic for transient failures.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from deepgram import DeepgramClient

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0

# Maximum file size: 2 GB (Deepgram limit)
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024

# Supported audio formats
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".webm", ".mp4"}


class TranscriptionError(Exception):
    """Raised when audio transcription fails."""

    pass


def _get_deepgram_api_key() -> str:
    """Retrieve the Deepgram API key from environment.

    Returns:
        The API key string.

    Raises:
        TranscriptionError: If the key is not set.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise TranscriptionError(
            "DEEPGRAM_API_KEY environment variable is not set. "
            "Set it before running transcription."
        )
    return api_key


def _validate_audio_file(audio_path: Path) -> None:
    """Validate that the audio file exists and is a supported format.

    Args:
        audio_path: Path to the audio file.

    Raises:
        TranscriptionError: If validation fails.
    """
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    if not audio_path.is_file():
        raise TranscriptionError(f"Path is not a file: {audio_path}")

    if audio_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise TranscriptionError(
            f"Unsupported audio format: {audio_path.suffix}. "
            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    file_size = audio_path.stat().st_size
    if file_size == 0:
        raise TranscriptionError(f"Audio file is empty: {audio_path}")

    if file_size > MAX_FILE_SIZE_BYTES:
        size_gb = file_size / (1024 * 1024 * 1024)
        raise TranscriptionError(
            f"Audio file too large: {size_gb:.2f} GB. "
            f"Maximum size is {MAX_FILE_SIZE_BYTES / (1024 * 1024 * 1024):.0f} GB."
        )


def transcribe_audio(
    audio_path: str | Path,
    language: str = "en",
    model: str = "nova-2",
    save_transcript: bool = True,
) -> str:
    """Transcribe an audio file using the Deepgram API.

    Sends the audio file to Deepgram for pre-recorded transcription.
    The transcript text is returned, and optionally saved to a .txt
    file alongside the original audio file.

    Args:
        audio_path: Path to the audio file to transcribe.
        language: Language code for transcription. Defaults to 'en'.
        model: Deepgram model to use. Defaults to 'nova-2'.
        save_transcript: If True, saves the transcript to a .txt file
            next to the audio file. Defaults to True.

    Returns:
        The full transcript text.

    Raises:
        TranscriptionError: If the file is invalid, the API call fails
            after all retries, or the response is empty.
    """
    audio_path = Path(audio_path).resolve()
    _validate_audio_file(audio_path)

    api_key = _get_deepgram_api_key()
    file_size_mb = audio_path.stat().st_size / (1024 * 1024)

    logger.info(
        "Starting transcription: %s (%.2f MB, format=%s, model=%s)",
        audio_path,
        file_size_mb,
        audio_path.suffix,
        model,
    )

    # Read the audio file into memory
    try:
        with open(audio_path, "rb") as f:
            audio_data = f.read()
    except OSError as exc:
        raise TranscriptionError(
            f"Failed to read audio file: {exc}"
        ) from exc

    # Attempt transcription with retries
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Transcription attempt %d/%d", attempt, MAX_RETRIES)
            client = DeepgramClient(api_key)
            response = client.listen.v1.media.transcribe_file(
                request=audio_data,
                model=model,
                language=language,
                smart_format=True,
                punctuate=True,
                paragraphs=True,
                utterances=True,
                diarize=True,
            )

            # Extract transcript text from response
            transcript = _extract_transcript(response)

            if not transcript or not transcript.strip():
                raise TranscriptionError(
                    "Deepgram returned an empty transcript. "
                    "The audio may be silent or unintelligible."
                )

            logger.info(
                "Transcription complete: %d characters, %d words",
                len(transcript),
                len(transcript.split()),
            )

            # Save transcript to file
            if save_transcript:
                transcript_path = audio_path.with_suffix(".txt")
                _save_transcript(transcript_path, transcript)

            return transcript

        except TranscriptionError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Transcription attempt %d failed: %s", attempt, exc
            )
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.info("Retrying in %.1f seconds...", delay)
                time.sleep(delay)

    raise TranscriptionError(
        f"Transcription failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _extract_transcript(response: object) -> str:
    """Extract the full transcript text from a Deepgram response.

    Args:
        response: The Deepgram API response object.

    Returns:
        The transcript text.

    Raises:
        TranscriptionError: If the response structure is unexpected.
    """
    try:
        results = response.results  # type: ignore[attr-defined]
        if results is None:
            raise TranscriptionError("Deepgram response has no results")

        channels = results.channels
        if not channels:
            raise TranscriptionError("Deepgram response has no channels")

        # Use paragraphs if available, otherwise fall back to transcript
        first_channel = channels[0]

        # Try to get paragraph-formatted text
        alternatives = first_channel.alternatives
        if not alternatives:
            raise TranscriptionError(
                "Deepgram response has no alternatives"
            )

        first_alt = alternatives[0]

        # Check for paragraphs (more readable format)
        paragraphs = getattr(first_alt, "paragraphs", None)
        if paragraphs and hasattr(paragraphs, "transcript"):
            transcript = paragraphs.transcript
            if transcript and transcript.strip():
                return transcript.strip()

        # Fall back to flat transcript
        transcript = getattr(first_alt, "transcript", None)
        if transcript and isinstance(transcript, str) and transcript.strip():
            return transcript.strip()

        raise TranscriptionError(
            "Could not extract transcript text from Deepgram response"
        )

    except (AttributeError, IndexError, TypeError) as exc:
        raise TranscriptionError(
            f"Unexpected Deepgram response structure: {exc}"
        ) from exc


def _save_transcript(transcript_path: Path, transcript: str) -> None:
    """Save transcript text to a file.

    Args:
        transcript_path: Path where the transcript file will be saved.
        transcript: The transcript text to write.
    """
    try:
        transcript_path.write_text(transcript, encoding="utf-8")
        logger.info("Transcript saved to: %s", transcript_path)
        print(f"Transcript saved: {transcript_path}")
    except OSError as exc:
        logger.error("Failed to save transcript file: %s", exc)
        print(f"Warning: Could not save transcript file: {exc}")
