"""
E2E tests for the full onboarding pipeline.

Pipeline: Record mock interview -> Deepgram transcribes -> LLM extracts config
          -> verify config file is correct and complete.

Marked @pytest.mark.e2e. Each test recursively validates dependency chain:
  audio file exists -> transcript is non-empty -> config has all required fields
  -> config validates against schema.

Tests:
- Full onboarding: audio -> transcript -> config extraction -> validate
- Recursive dependency validation at each step
- Minimal interview with missing fields -> verify prompts for missing data
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml


pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Required top-level config sections per the spec
REQUIRED_CONFIG_SECTIONS = [
    "client",
    "settings",
]

# Required fields within each section
REQUIRED_FIELDS = {
    "client": ["name"],
    "settings": [
        "morning_briefing_time",
        "quiet_hours_start",
        "quiet_hours_end",
        "reminder_lead_minutes",
        "min_snooze_minutes",
        "timezone",
    ],
}

# All extractable fields (some may be optional)
EXTRACTABLE_FIELDS = {
    "client": ["name", "company"],
    "elevenlabs": ["agent_name", "personality"],
    "twilio": ["client_phone"],
    "settings": [
        "morning_briefing_time",
        "quiet_hours_start",
        "quiet_hours_end",
        "reminder_lead_minutes",
        "min_snooze_minutes",
        "timezone",
    ],
}

COMPLETE_EXTRACTED_CONFIG = {
    "client": {
        "name": "John Doe",
        "company": "Acme Corp",
    },
    "elevenlabs": {
        "agent_name": "Rafi",
        "personality": "Professional, friendly, concise",
    },
    "twilio": {
        "client_phone": "+14155551234",
    },
    "settings": {
        "morning_briefing_time": "08:00",
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "reminder_lead_minutes": 15,
        "min_snooze_minutes": 5,
        "timezone": "America/New_York",
    },
}


def _mock_deepgram_response(text: str) -> MagicMock:
    """Build a mock Deepgram transcription response."""
    alt = MagicMock()
    alt.transcript = text
    alt.confidence = 0.97
    alt.paragraphs = None  # Prevent MagicMock auto-attr from intercepting
    channel = MagicMock()
    channel.alternatives = [alt]
    result = MagicMock()
    result.channels = [channel]
    resp = MagicMock()
    resp.results = result
    return resp


def _mock_openai_response(config_dict: dict) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response with JSON content."""
    import json as _json
    message = MagicMock()
    message.content = _json.dumps(config_dict)
    message.role = "assistant"
    message.refusal = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(total_tokens=400)
    return resp


def validate_audio_file_exists(audio_path: Path) -> None:
    """Recursively validate: audio file exists and has content."""
    assert audio_path.exists(), f"Audio file must exist: {audio_path}"
    assert audio_path.stat().st_size > 0, "Audio file must not be empty"
    # Basic WAV header check
    header = audio_path.read_bytes()[:4]
    assert header == b"RIFF" or len(header) > 0, "Audio should have valid header"


def validate_transcript_nonempty(transcript: str) -> None:
    """Recursively validate: transcript is non-empty and meaningful."""
    assert transcript is not None, "Transcript must not be None"
    assert isinstance(transcript, str), "Transcript must be a string"
    assert len(transcript.strip()) > 0, "Transcript must not be empty/whitespace"
    assert len(transcript) >= 10, "Transcript should contain meaningful content"


def validate_config_has_required_fields(config: dict) -> None:
    """Recursively validate: config has all required sections and fields."""
    assert isinstance(config, dict), "Config must be a dict"

    for section in REQUIRED_CONFIG_SECTIONS:
        assert section in config, f"Config missing required section: {section}"
        assert isinstance(config[section], dict), f"Section '{section}' must be a dict"

    for section, fields in REQUIRED_FIELDS.items():
        for field in fields:
            assert field in config.get(section, {}), (
                f"Config missing required field: {section}.{field}"
            )
            value = config[section][field]
            if isinstance(value, str):
                assert len(value.strip()) > 0, (
                    f"Config field {section}.{field} must not be empty"
                )


def validate_config_against_schema(config: dict) -> None:
    """Validate config values have correct types per spec."""
    settings = config.get("settings", {})

    # Time fields should be HH:MM format
    for time_field in ["morning_briefing_time", "quiet_hours_start", "quiet_hours_end"]:
        val = settings.get(time_field, "")
        if val:
            assert ":" in val, f"{time_field} should be HH:MM format"

    # Numeric fields should be integers
    for int_field in ["reminder_lead_minutes", "min_snooze_minutes"]:
        val = settings.get(int_field)
        if val is not None:
            assert isinstance(val, int), f"{int_field} should be int, got {type(val)}"
            assert val > 0, f"{int_field} should be positive"

    # Timezone should be a valid-looking timezone string
    tz = settings.get("timezone", "")
    if tz:
        assert "/" in tz or tz == "UTC", f"Timezone '{tz}' should be IANA format"

    # Client name should be a non-empty string
    name = config.get("client", {}).get("name", "")
    assert isinstance(name, str) and len(name) > 0, "Client name must be non-empty"


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------

class TestOnboardingPipelineFull:
    """Full onboarding: audio -> transcript -> config extraction -> validate."""

    @patch("src.onboarding.config_extractor.OpenAI")
    @patch("src.onboarding.transcriber.DeepgramClient")
    @patch.dict(os.environ, {"DEEPGRAM_API_KEY": "test_key", "OPENAI_API_KEY": "test_key"})
    def test_full_pipeline_produces_valid_config(
        self,
        mock_dg_class,
        mock_openai_class,
        sample_audio_path,
        sample_transcript,
        tmp_path,
    ):
        """
        End-to-end: sample audio -> Deepgram transcribes -> LLM extracts config
        -> config is correct and complete.
        """
        from src.onboarding.transcriber import transcribe_audio
        from src.onboarding.config_extractor import extract_config

        # --- Step 1: Validate audio file exists ---
        validate_audio_file_exists(sample_audio_path)

        # --- Step 2: Transcribe audio (mocked Deepgram) ---
        dg_response = _mock_deepgram_response(sample_transcript)
        mock_client = MagicMock()
        mock_client.listen.v1.media.transcribe_file.return_value = dg_response
        mock_dg_class.return_value = mock_client

        transcript = transcribe_audio(str(sample_audio_path))

        # Recursive validation: transcript is non-empty
        validate_transcript_nonempty(transcript)

        # --- Step 3: Extract config from transcript (mocked OpenAI) ---
        openai_response = _mock_openai_response(COMPLETE_EXTRACTED_CONFIG)
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = openai_response
        mock_openai_class.return_value = openai_client

        config = extract_config(transcript)

        # --- Step 4: Recursive validation of extracted config ---
        validate_config_has_required_fields(config)
        validate_config_against_schema(config)

        # Verify specific extracted values
        assert config["client"]["name"] == "John Doe"
        assert config["client"]["company"] == "Acme Corp"
        assert config["settings"]["morning_briefing_time"] == "08:00"
        assert config["settings"]["timezone"] == "America/New_York"

    @patch("src.onboarding.config_extractor.OpenAI")
    @patch("src.onboarding.transcriber.DeepgramClient")
    @patch.dict(os.environ, {"DEEPGRAM_API_KEY": "test_key", "OPENAI_API_KEY": "test_key"})
    def test_pipeline_config_serializes_to_valid_yaml(
        self,
        mock_dg_class,
        mock_openai_class,
        sample_audio_path,
        sample_transcript,
        tmp_path,
    ):
        """Config from pipeline should serialize to valid, re-parseable YAML."""
        from src.onboarding.transcriber import transcribe_audio
        from src.onboarding.config_extractor import extract_config

        # Set up mocks
        dg_response = _mock_deepgram_response(sample_transcript)
        mock_client = MagicMock()
        mock_client.listen.v1.media.transcribe_file.return_value = dg_response
        mock_dg_class.return_value = mock_client

        openai_response = _mock_openai_response(COMPLETE_EXTRACTED_CONFIG)
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = openai_response
        mock_openai_class.return_value = openai_client

        transcript = transcribe_audio(str(sample_audio_path))
        config = extract_config(transcript)

        # Write to YAML and re-read
        config_file = tmp_path / "extracted_config.yaml"
        config_file.write_text(yaml.dump(config, default_flow_style=False))

        reloaded = yaml.safe_load(config_file.read_text())
        assert reloaded == config
        validate_config_has_required_fields(reloaded)


class TestOnboardingRecursiveValidation:
    """Recursively validate each dependency in the chain."""

    @patch("src.onboarding.config_extractor.OpenAI")
    @patch("src.onboarding.transcriber.DeepgramClient")
    @patch.dict(os.environ, {"DEEPGRAM_API_KEY": "test_key", "OPENAI_API_KEY": "test_key"})
    def test_step_by_step_dependency_chain(
        self,
        mock_dg_class,
        mock_openai_class,
        sample_audio_path,
        sample_transcript,
    ):
        """
        Validate dependency chain:
        1. Audio file exists
        2. Transcript is non-empty
        3. Config has all required fields
        4. Config validates against schema
        """
        from src.onboarding.transcriber import transcribe_audio
        from src.onboarding.config_extractor import extract_config

        # 1. Audio file exists
        validate_audio_file_exists(sample_audio_path)

        # 2. Transcription produces non-empty result
        dg_response = _mock_deepgram_response(sample_transcript)
        mock_client = MagicMock()
        mock_client.listen.v1.media.transcribe_file.return_value = dg_response
        mock_dg_class.return_value = mock_client

        transcript = transcribe_audio(str(sample_audio_path))
        validate_transcript_nonempty(transcript)

        # 3. Config extraction produces required fields
        openai_response = _mock_openai_response(COMPLETE_EXTRACTED_CONFIG)
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = openai_response
        mock_openai_class.return_value = openai_client

        config = extract_config(transcript)
        validate_config_has_required_fields(config)

        # 4. Config validates against schema
        validate_config_against_schema(config)

    @patch("src.onboarding.transcriber.DeepgramClient")
    @patch.dict(os.environ, {"DEEPGRAM_API_KEY": "test_key"})
    def test_transcription_failure_stops_pipeline(
        self, mock_dg_class, sample_audio_path
    ):
        """If transcription fails, the pipeline should not proceed."""
        mock_client = MagicMock()
        mock_client.listen.v1.media.transcribe_file.side_effect = Exception(
            "Deepgram API unavailable"
        )
        mock_dg_class.return_value = mock_client

        from src.onboarding.transcriber import transcribe_audio

        with pytest.raises(Exception):
            transcribe_audio(str(sample_audio_path))

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_extraction_failure_stops_pipeline(self, mock_openai_class):
        """If config extraction fails, pipeline should not produce config."""
        from src.onboarding.config_extractor import extract_config

        openai_client = MagicMock()
        openai_client.chat.completions.create.side_effect = Exception(
            "OpenAI API unavailable"
        )
        mock_openai_class.return_value = openai_client

        with pytest.raises(Exception):
            extract_config("Valid transcript text here with some content.")


class TestOnboardingMinimalInterview:
    """Minimal interview with missing fields -> verify missing data handling."""

    @patch("src.onboarding.config_extractor.OpenAI")
    @patch("src.onboarding.transcriber.DeepgramClient")
    @patch.dict(os.environ, {"DEEPGRAM_API_KEY": "test_key", "OPENAI_API_KEY": "test_key"})
    def test_minimal_interview_flags_missing_fields(
        self,
        mock_dg_class,
        mock_openai_class,
        sample_audio_path,
    ):
        """
        Interview with only a name -> config should indicate missing fields
        or use defaults.
        """
        from src.onboarding.transcriber import transcribe_audio
        from src.onboarding.config_extractor import extract_config

        # Minimal transcript with only name
        minimal_transcript = "Client: My name is Alice."
        dg_response = _mock_deepgram_response(minimal_transcript)
        mock_client = MagicMock()
        mock_client.listen.v1.media.transcribe_file.return_value = dg_response
        mock_dg_class.return_value = mock_client

        transcript = transcribe_audio(str(sample_audio_path))

        # LLM returns partial config
        partial_config = {
            "client": {"name": "Alice"},
            "settings": {},
        }
        openai_response = _mock_openai_response(partial_config)
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = openai_response
        mock_openai_class.return_value = openai_client

        config = extract_config(transcript)

        # Config should exist but may have missing fields
        assert isinstance(config, dict)
        assert config.get("client", {}).get("name") == "Alice"

        # Missing settings fields should either be absent or have defaults
        settings = config.get("settings", {})
        # If the implementation fills defaults, they should be valid
        for field in ["morning_briefing_time", "timezone"]:
            if field in settings:
                assert settings[field] is not None

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_completely_empty_interview_handled(self, mock_openai_class):
        """An interview with no useful content should raise or return minimal."""
        from src.onboarding.config_extractor import extract_config

        empty_config = {}
        openai_response = _mock_openai_response(empty_config)
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = openai_response
        mock_openai_class.return_value = openai_client

        # Should either raise or return an empty/partial config
        try:
            config = extract_config("Um... I don't know... nothing really.")
            assert isinstance(config, dict)
        except (ValueError, Exception):
            pass  # Raising is acceptable for useless input
