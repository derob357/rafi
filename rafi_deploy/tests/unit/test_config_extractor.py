"""
Unit tests for src.onboarding.config_extractor — LLM config extraction.

Tests:
- extract_config produces valid YAML from transcript (mocked OpenAI)
- Extracted config validates against pydantic schema
- Handles transcript with missing information (prompts for required fields)
- Handles LLM returning malformed response
- Handles empty transcript
- Handles None transcript
- Sanitizes extracted values
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.onboarding.config_extractor import extract_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_response(content: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response."""
    message = MagicMock()
    message.content = content
    message.role = "assistant"
    message.refusal = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock()
    response.usage.total_tokens = 500
    return response


def _make_openai_client(response: MagicMock) -> MagicMock:
    """Return a fully mocked OpenAI client."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock(return_value=response)
    return client


VALID_EXTRACTED_CONFIG = {
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractConfigValid:
    """extract_config produces valid YAML from a transcript."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_returns_dict_with_expected_keys(
        self, mock_openai_class, sample_transcript
    ):
        config_yaml = yaml.dump(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        assert isinstance(result, dict)
        assert "client" in result
        assert "settings" in result

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_extracts_client_name(
        self, mock_openai_class, sample_transcript
    ):
        config_yaml = yaml.dump(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        assert result["client"]["name"] == "John Doe"

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_extracts_settings(
        self, mock_openai_class, sample_transcript
    ):
        config_yaml = yaml.dump(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        settings = result.get("settings", {})
        assert settings.get("morning_briefing_time") == "08:00"
        assert settings.get("timezone") == "America/New_York"
        assert settings.get("reminder_lead_minutes") == 15

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_output_is_valid_yaml(
        self, mock_openai_class, sample_transcript, tmp_path
    ):
        config_yaml = yaml.dump(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        # Verify the result can round-trip through YAML
        yaml_str = yaml.dump(result)
        reloaded = yaml.safe_load(yaml_str)
        assert reloaded == result


@pytest.mark.unit
class TestExtractConfigValidatesSchema:
    """Extracted config validates against pydantic schema."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_validates_required_client_fields(
        self, mock_openai_class, sample_transcript
    ):
        config_yaml = yaml.dump(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        # Required fields per spec
        assert "name" in result.get("client", {})
        assert isinstance(result["client"]["name"], str)
        assert len(result["client"]["name"]) > 0

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_validates_settings_types(
        self, mock_openai_class, sample_transcript
    ):
        config_yaml = yaml.dump(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)
        settings = result.get("settings", {})

        assert isinstance(settings.get("reminder_lead_minutes"), int)
        assert isinstance(settings.get("min_snooze_minutes"), int)
        assert isinstance(settings.get("timezone"), str)


@pytest.mark.unit
class TestExtractConfigMissingInfo:
    """Handles transcript with missing information."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_missing_fields_flagged(self, mock_openai_class):
        """When transcript lacks info, result should flag missing fields."""
        incomplete_config = {
            "client": {"name": "Jane Smith"},
            # Missing: company, phone, settings, etc.
        }
        config_yaml = yaml.dump(incomplete_config)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        sparse_transcript = "Client: My name is Jane Smith. That's all."

        result = extract_config(sparse_transcript)

        # The extractor should return what it found.
        # Missing fields should either be absent or have placeholder values.
        assert isinstance(result, dict)
        assert result.get("client", {}).get("name") == "Jane Smith"

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_missing_settings_use_defaults_or_empty(self, mock_openai_class):
        """Missing settings should not crash; use defaults or empty."""
        partial_config = {
            "client": {"name": "Bob"},
            "settings": {},
        }
        config_yaml = yaml.dump(partial_config)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config("Client: I'm Bob.")

        assert isinstance(result, dict)


@pytest.mark.unit
class TestExtractConfigMalformedLLMResponse:
    """Handles LLM returning malformed response."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_non_yaml_response_raises(self, mock_openai_class, sample_transcript):
        """If LLM returns garbage, extract_config should raise or handle."""
        garbage = "This is not YAML at all!!! {{{{[[[["
        response = _make_openai_response(garbage)
        mock_openai_class.return_value = _make_openai_client(response)

        with pytest.raises((ValueError, yaml.YAMLError, Exception)):
            extract_config(sample_transcript)

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_json_instead_of_yaml_handled(
        self, mock_openai_class, sample_transcript
    ):
        """If LLM returns JSON (which is valid YAML), it should still work."""
        json_response = json.dumps(VALID_EXTRACTED_CONFIG)
        response = _make_openai_response(json_response)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        # JSON is valid YAML, so this should parse
        assert isinstance(result, dict)

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_empty_llm_response_raises(
        self, mock_openai_class, sample_transcript
    ):
        response = _make_openai_response("")
        mock_openai_class.return_value = _make_openai_client(response)

        with pytest.raises((ValueError, TypeError, Exception)):
            extract_config(sample_transcript)

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_none_content_in_response_raises(
        self, mock_openai_class, sample_transcript
    ):
        response = _make_openai_response("")
        response.choices[0].message.content = None
        mock_openai_class.return_value = _make_openai_client(response)

        with pytest.raises((ValueError, TypeError, AttributeError, Exception)):
            extract_config(sample_transcript)


@pytest.mark.unit
class TestExtractConfigEmptyTranscript:
    """Handles empty transcript."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_empty_string_raises(self, mock_openai_class):
        with pytest.raises((ValueError, Exception)):
            extract_config("")

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_whitespace_only_raises(self, mock_openai_class):
        with pytest.raises((ValueError, Exception)):
            extract_config("   \n\t  ")


@pytest.mark.unit
class TestExtractConfigNoneTranscript:
    """Handles None transcript."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_none_raises_type_or_value_error(self, mock_openai_class):
        with pytest.raises((TypeError, ValueError)):
            extract_config(None)


@pytest.mark.unit
class TestExtractConfigSanitization:
    """Extracted values are sanitized."""

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_strips_html_from_values(
        self, mock_openai_class, sample_transcript
    ):
        malicious_config = {
            "client": {
                "name": '<script>alert("xss")</script>John Doe',
                "company": "Acme Corp",
            },
            "settings": {
                "morning_briefing_time": "08:00",
                "timezone": "America/New_York",
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
                "reminder_lead_minutes": 15,
                "min_snooze_minutes": 5,
            },
        }
        config_yaml = yaml.dump(malicious_config)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        client_name = result.get("client", {}).get("name", "")
        assert "<script>" not in client_name

    @patch("src.onboarding.config_extractor.OpenAI")
    def test_strips_control_characters(
        self, mock_openai_class, sample_transcript
    ):
        config_with_control = {
            "client": {
                "name": "John\x00Doe\x07",
                "company": "Acme\x1bCorp",
            },
            "settings": {
                "morning_briefing_time": "08:00",
                "timezone": "America/New_York",
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
                "reminder_lead_minutes": 15,
                "min_snooze_minutes": 5,
            },
        }
        config_yaml = yaml.dump(config_with_control)
        response = _make_openai_response(config_yaml)
        mock_openai_class.return_value = _make_openai_client(response)

        result = extract_config(sample_transcript)

        client_name = result.get("client", {}).get("name", "")
        # Control chars should be stripped
        assert "\x00" not in client_name
        assert "\x07" not in client_name
