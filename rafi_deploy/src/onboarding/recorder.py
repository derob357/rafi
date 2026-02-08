"""Audio recording functionality for onboarding interviews.

Records audio from the system microphone to a WAV file. The recording
runs until the user presses Ctrl+C, at which point the audio is saved
and the path is returned.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)

# Recording defaults
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_SUBTYPE = "PCM_16"
DEFAULT_BLOCKSIZE = 1024


class RecordingError(Exception):
    """Raised when a recording operation fails."""

    pass


def _format_duration(seconds: float) -> str:
    """Format elapsed seconds as MM:SS.

    Args:
        seconds: Number of elapsed seconds.

    Returns:
        Formatted string like '03:45'.
    """
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


def record_interview(
    output_path: str | Path,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
) -> Path:
    """Record audio from the microphone and save as a WAV file.

    Starts recording immediately and displays the elapsed duration in
    real-time on stdout. The recording is stopped by pressing Ctrl+C
    (SIGINT). The captured audio is then written to the specified path
    as a WAV file.

    Args:
        output_path: Filesystem path where the WAV file will be saved.
            Parent directory must exist.
        sample_rate: Sample rate in Hz. Defaults to 44100.
        channels: Number of audio channels. Defaults to 1 (mono).

    Returns:
        Resolved Path to the saved WAV file.

    Raises:
        RecordingError: If the microphone cannot be opened, the output
            directory does not exist, or the file cannot be written.
    """
    output = Path(output_path).resolve()

    if not output.parent.exists():
        raise RecordingError(
            f"Output directory does not exist: {output.parent}"
        )

    if output.suffix.lower() != ".wav":
        output = output.with_suffix(".wav")
        logger.info("Output path adjusted to WAV extension: %s", output)

    # Verify that a recording device is available
    try:
        device_info = sd.query_devices(kind="input")
        if device_info is None:
            raise RecordingError("No input audio device found")
        logger.info(
            "Using input device: %s",
            device_info.get("name", "unknown"),
        )
    except sd.PortAudioError as exc:
        raise RecordingError(f"Cannot access audio device: {exc}") from exc

    # Container for recorded audio chunks
    audio_chunks: list[np.ndarray] = []
    recording_active = threading.Event()
    recording_active.set()
    start_time: float = 0.0

    def audio_callback(
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """Called by sounddevice for each block of audio data."""
        if status:
            logger.warning("Audio callback status: %s", status)
        if recording_active.is_set():
            audio_chunks.append(indata.copy())

    def signal_handler(signum: int, frame: object) -> None:
        """Handle Ctrl+C to stop recording gracefully."""
        recording_active.clear()

    # Install signal handler
    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        logger.info("Starting recording to %s", output)
        print(f"\nRecording to: {output}")
        print("Press Ctrl+C to stop recording.\n")

        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            blocksize=DEFAULT_BLOCKSIZE,
            callback=audio_callback,
        )

        with stream:
            start_time = time.monotonic()

            while recording_active.is_set():
                elapsed = time.monotonic() - start_time
                sys.stdout.write(
                    f"\r  Recording... {_format_duration(elapsed)}  "
                )
                sys.stdout.flush()
                time.sleep(0.1)

        # Print final duration
        total_duration = time.monotonic() - start_time
        print(f"\n\nRecording stopped. Duration: {_format_duration(total_duration)}")

    except sd.PortAudioError as exc:
        raise RecordingError(f"Audio recording failed: {exc}") from exc
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)

    if not audio_chunks:
        raise RecordingError("No audio data was captured")

    # Concatenate all chunks and write to file
    try:
        audio_data = np.concatenate(audio_chunks, axis=0)
        sf.write(
            str(output),
            audio_data,
            sample_rate,
            subtype=DEFAULT_SUBTYPE,
        )
        file_size_mb = output.stat().st_size / (1024 * 1024)
        logger.info(
            "Recording saved: %s (%.2f MB, %.1f seconds)",
            output,
            file_size_mb,
            total_duration,
        )
        print(f"Saved: {output} ({file_size_mb:.2f} MB)")
    except (OSError, sf.SoundFileError) as exc:
        raise RecordingError(f"Failed to write audio file: {exc}") from exc

    return output
