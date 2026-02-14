"""Unit tests for Deepgram STT retry and parsing behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from src.voice.deepgram_stt import DeepgramSTT


@pytest.mark.asyncio
async def test_transcribe_file_returns_none_for_missing_path(tmp_path: Path):
    stt = DeepgramSTT(api_key="dg_key")

    result = await stt.transcribe_file(str(tmp_path / "missing.ogg"))

    assert result is None


@pytest.mark.asyncio
async def test_transcribe_file_returns_none_for_empty_file(tmp_path: Path):
    stt = DeepgramSTT(api_key="dg_key")
    file_path = tmp_path / "empty.ogg"
    file_path.write_bytes(b"")

    result = await stt.transcribe_file(str(file_path))

    assert result is None


@pytest.mark.asyncio
async def test_transcribe_file_success_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    stt = DeepgramSTT(api_key="dg_key")
    file_path = tmp_path / "audio.ogg"
    file_path.write_bytes(b"dummy-audio")

    monkeypatch.setattr(stt, "_send_request", AsyncMock(return_value="hello world"))

    result = await stt.transcribe_file(str(file_path))

    assert result == "hello world"


@pytest.mark.asyncio
async def test_transcribe_file_retries_on_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    stt = DeepgramSTT(api_key="dg_key")
    file_path = tmp_path / "audio.ogg"
    file_path.write_bytes(b"dummy-audio")

    request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError("500", request=request, response=response)

    monkeypatch.setattr("src.voice.deepgram_stt.RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(stt, "_send_request", AsyncMock(side_effect=[error, "after-retry"]))

    result = await stt.transcribe_file(str(file_path))

    assert result == "after-retry"


def test_extract_transcript_parses_valid_shape() -> None:
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {"transcript": "hello from deepgram"}
                    ]
                }
            ]
        }
    }

    result = DeepgramSTT._extract_transcript(payload)
    assert result == "hello from deepgram"


def test_extract_transcript_handles_missing_shape() -> None:
    assert DeepgramSTT._extract_transcript({}) is None
    assert DeepgramSTT._extract_transcript({"results": {}}) is None
    assert DeepgramSTT._extract_transcript({"results": {"channels": []}}) is None
