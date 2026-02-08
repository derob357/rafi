"""Tests for src/config/loader.py — configuration loading and validation.

Covers:
- Valid YAML loads successfully into AppConfig
- Missing required fields raise clear errors
- Invalid values (bad phone, bad time format) raise errors
- Optional fields have correct defaults
- Timezone validation
"""

from __future__ import annotations

import copy
import textwrap
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from src.config.loader import (
    AppConfig,
    ClientConfig,
    ElevenLabsConfig,
    LLMConfig,
    SettingsConfig,
    SupabaseConfig,
    TelegramConfig,
    TwilioConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, data: Dict[str, Any], filename: str = "config.yaml") -> str:
    """Write a dict as YAML to tmp_path and return the file path."""
    filepath = tmp_path / filename
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return str(filepath)


# ---------------------------------------------------------------------------
# Test: Valid YAML loads successfully
# ---------------------------------------------------------------------------


class TestValidConfigLoad:
    """Valid configuration loads and produces the correct AppConfig."""

    def test_load_full_config(self, tmp_yaml_config: str, test_config_dict: Dict[str, Any]):
        config = load_config(tmp_yaml_config)
        assert config.client.name == test_config_dict["client"]["name"]
        assert config.telegram.user_id == test_config_dict["telegram"]["user_id"]
        assert config.twilio.phone_number == test_config_dict["twilio"]["phone_number"]
        assert config.llm.provider == "openai"
        assert config.settings.timezone == "America/New_York"

    def test_returns_app_config_instance(self, tmp_yaml_config: str):
        config = load_config(tmp_yaml_config)
        assert isinstance(config, AppConfig)

    def test_client_name_preserved(self, tmp_yaml_config: str):
        config = load_config(tmp_yaml_config)
        assert config.client.name == "Test User"

    def test_settings_section_parsed(self, tmp_yaml_config: str):
        config = load_config(tmp_yaml_config)
        assert config.settings.morning_briefing_time == "08:00"
        assert config.settings.reminder_lead_minutes == 15


# ---------------------------------------------------------------------------
# Test: Missing required fields
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    """Missing required fields raise ValueError with clear messages."""

    def test_missing_client_section(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["client"]
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)client"):
            load_config(path)

    def test_missing_telegram_section(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["telegram"]
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)telegram"):
            load_config(path)

    def test_missing_client_name(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["client"]["name"]
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)name"):
            load_config(path)

    def test_missing_telegram_bot_token(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["telegram"]["bot_token"]
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)bot_token"):
            load_config(path)

    def test_missing_llm_api_key(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["llm"]["api_key"]
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)api_key"):
            load_config(path)

    def test_missing_supabase_url(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["supabase"]["url"]
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)url"):
            load_config(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_empty_yaml_file(self, tmp_path):
        filepath = tmp_path / "empty.yaml"
        filepath.write_text("")
        with pytest.raises(ValueError):
            load_config(str(filepath))


# ---------------------------------------------------------------------------
# Test: Invalid values
# ---------------------------------------------------------------------------


class TestInvalidValues:
    """Invalid field values raise clear errors."""

    def test_invalid_phone_no_plus(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["twilio"]["phone_number"] = "15551234567"  # missing +
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)e.164|\\+"):
            load_config(path)

    def test_invalid_account_sid(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["twilio"]["account_sid"] = "XX_invalid_sid"  # must start with AC
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)AC"):
            load_config(path)

    def test_invalid_time_format_no_colon(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["morning_briefing_time"] = "0800"
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)hh:mm|time"):
            load_config(path)

    def test_invalid_time_format_bad_hour(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["quiet_hours_start"] = "25:00"
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)time|invalid"):
            load_config(path)

    def test_invalid_time_format_bad_minute(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["quiet_hours_end"] = "07:61"
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)time|invalid"):
            load_config(path)

    def test_invalid_bot_token_no_colon(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["telegram"]["bot_token"] = "no_colon_in_this_token"
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)colon"):
            load_config(path)

    def test_invalid_llm_provider(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["llm"]["provider"] = "mistral"
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)provider"):
            load_config(path)

    def test_invalid_supabase_url_no_https(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["supabase"]["url"] = "http://insecure.supabase.co"
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="(?i)https"):
            load_config(path)

    def test_negative_user_id(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["telegram"]["user_id"] = -1
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError):
            load_config(path)

    def test_invalid_yaml_syntax(self, tmp_path):
        filepath = tmp_path / "bad.yaml"
        filepath.write_text("key: [unbalanced bracket\n  nope:")
        with pytest.raises(ValueError, match="(?i)yaml"):
            load_config(str(filepath))


# ---------------------------------------------------------------------------
# Test: Optional fields have correct defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    """Optional fields use correct default values when omitted."""

    def test_settings_defaults_when_omitted(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["settings"]
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.settings.morning_briefing_time == "08:00"
        assert config.settings.quiet_hours_start == "22:00"
        assert config.settings.quiet_hours_end == "07:00"
        assert config.settings.reminder_lead_minutes == 15
        assert config.settings.min_snooze_minutes == 5
        assert config.settings.save_to_disk is False
        assert config.settings.timezone == "America/New_York"

    def test_company_defaults_empty(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["client"]["company"]
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.client.company == ""

    def test_llm_defaults(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["llm"]["model"]
        del data["llm"]["temperature"]
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.llm.model == "gpt-4o"
        assert config.llm.temperature == 0.7

    def test_elevenlabs_agent_name_default(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["elevenlabs"]["agent_name"]
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.elevenlabs.agent_name == "Rafi"

    def test_google_refresh_token_default_empty(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        del data["google"]["refresh_token"]
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.google.refresh_token == ""


# ---------------------------------------------------------------------------
# Test: Timezone validation
# ---------------------------------------------------------------------------


class TestTimezoneValidation:
    """Timezone values are accepted or rejected as expected."""

    def test_valid_timezone_new_york(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["timezone"] = "America/New_York"
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.settings.timezone == "America/New_York"

    def test_valid_timezone_utc(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["timezone"] = "UTC"
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.settings.timezone == "UTC"

    def test_valid_timezone_los_angeles(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["timezone"] = "America/Los_Angeles"
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.settings.timezone == "America/Los_Angeles"

    def test_valid_timezone_tokyo(self, tmp_path, test_config_dict):
        data = copy.deepcopy(test_config_dict)
        data["settings"]["timezone"] = "Asia/Tokyo"
        path = _write_yaml(tmp_path, data)
        config = load_config(path)
        assert config.settings.timezone == "Asia/Tokyo"
