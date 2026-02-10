"""Configuration loader with Pydantic validation.

Loads client configuration from a YAML file, validates all fields,
and provides typed access to configuration values.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class ClientConfig(BaseModel):
    """Client identity configuration."""

    name: str = Field(..., min_length=1, description="Client full name")
    company: str = Field(default="", description="Client company name")


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    bot_token: str = Field(..., min_length=10, description="Telegram bot token from BotFather")
    user_id: int = Field(..., gt=0, description="Authorized Telegram user ID")

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("Bot token must contain a colon separator (format: 'ID:TOKEN')")
        return v


class TwilioConfig(BaseModel):
    """Twilio voice configuration."""

    account_sid: str = Field(..., min_length=2, description="Twilio account SID")
    auth_token: str = Field(..., min_length=2, description="Twilio auth token")
    phone_number: str = Field(..., description="Twilio phone number (E.164 format)")
    client_phone: str = Field(..., description="Client phone number for outbound calls")

    @field_validator("account_sid")
    @classmethod
    def validate_account_sid(cls, v: str) -> str:
        if not v.startswith("AC"):
            raise ValueError("Twilio account SID must start with 'AC'")
        return v

    @field_validator("phone_number", "client_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError("Phone numbers must be in E.164 format (start with '+')")
        return v


class ElevenLabsConfig(BaseModel):
    """ElevenLabs Conversational AI configuration."""

    api_key: str = Field(..., min_length=2, description="ElevenLabs API key")
    voice_id: str = Field(..., min_length=2, description="ElevenLabs voice ID")
    agent_name: str = Field(default="Rafi", description="Name the agent uses for itself")
    personality: str = Field(
        default="Professional, friendly, concise",
        description="Personality instructions for the agent",
    )


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openai", description="LLM provider: openai or anthropic")
    model: str = Field(default="gpt-4o", description="Model identifier")
    api_key: str = Field(..., min_length=2, description="LLM API key")
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model identifier",
    )
    max_tokens: int = Field(default=4096, gt=0, description="Max tokens for LLM response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="LLM temperature")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"openai", "anthropic"}
        if v.lower() not in allowed:
            raise ValueError(f"LLM provider must be one of: {allowed}")
        return v.lower()


class GoogleConfig(BaseModel):
    """Google API OAuth configuration."""

    client_id: str = Field(..., min_length=2, description="Google OAuth client ID")
    client_secret: str = Field(..., min_length=2, description="Google OAuth client secret")
    refresh_token: str = Field(default="", description="Google OAuth refresh token (populated after OAuth)")


class SupabaseConfig(BaseModel):
    """Supabase database configuration."""

    url: str = Field(..., min_length=5, description="Supabase project URL")
    anon_key: str = Field(..., min_length=2, description="Supabase anonymous key")
    service_role_key: str = Field(..., min_length=2, description="Supabase service role key")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Supabase URL must start with 'https://'")
        return v


class DeepgramConfig(BaseModel):
    """Deepgram STT configuration."""

    api_key: str = Field(..., min_length=2, description="Deepgram API key")
    model: str = Field(default="nova-2", description="Deepgram model")
    language: str = Field(default="en-US", description="Language code")


class WeatherConfig(BaseModel):
    """WeatherAPI.com configuration."""

    api_key: str = Field(..., min_length=2, description="WeatherAPI.com API key")


class SettingsConfig(BaseModel):
    """Runtime settings with defaults."""

    morning_briefing_time: str = Field(
        default="08:00",
        description="Morning briefing time in HH:MM format",
    )
    quiet_hours_start: str = Field(
        default="22:00",
        description="Quiet hours start in HH:MM format",
    )
    quiet_hours_end: str = Field(
        default="07:00",
        description="Quiet hours end in HH:MM format",
    )
    reminder_lead_minutes: int = Field(
        default=15,
        ge=1,
        le=120,
        description="Minutes before event to send reminder",
    )
    min_snooze_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Minimum snooze duration in minutes",
    )
    save_to_disk: bool = Field(
        default=False,
        description="Whether to save logs/transcripts to disk",
    )
    timezone: str = Field(
        default="America/New_York",
        description="Client timezone (IANA format)",
    )

    @field_validator("morning_briefing_time", "quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"Time must be in HH:MM format, got: {v}")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            raise ValueError(f"Time components must be integers, got: {v}")
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time value: {v}")
        return v


class AppConfig(BaseModel):
    """Root application configuration combining all sections."""

    client: ClientConfig
    telegram: TelegramConfig
    twilio: TwilioConfig
    elevenlabs: ElevenLabsConfig
    llm: LLMConfig
    google: GoogleConfig
    supabase: SupabaseConfig
    deepgram: DeepgramConfig
    weather: WeatherConfig
    settings: SettingsConfig = Field(default_factory=SettingsConfig)


# Mapping of environment variable names to (yaml_section, yaml_key) paths.
# When an env var is set, it overrides the corresponding YAML value.
_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "TELEGRAM_BOT_TOKEN": ("telegram", "bot_token"),
    "TWILIO_ACCOUNT_SID": ("twilio", "account_sid"),
    "TWILIO_AUTH_TOKEN": ("twilio", "auth_token"),
    "TWILIO_PHONE_NUMBER": ("twilio", "phone_number"),
    "ELEVENLABS_API_KEY": ("elevenlabs", "api_key"),
    "ELEVENLABS_VOICE_ID": ("elevenlabs", "voice_id"),
    "LLM_API_KEY": ("llm", "api_key"),
    "GOOGLE_CLIENT_ID": ("google", "client_id"),
    "GOOGLE_CLIENT_SECRET": ("google", "client_secret"),
    "SUPABASE_URL": ("supabase", "url"),
    "SUPABASE_ANON_KEY": ("supabase", "anon_key"),
    "SUPABASE_SERVICE_ROLE_KEY": ("supabase", "service_role_key"),
    "DEEPGRAM_API_KEY": ("deepgram", "api_key"),
    "WEATHER_API_KEY": ("weather", "api_key"),
}


def _apply_env_overrides(raw_config: dict) -> dict:
    """Override YAML config values with environment variables when set."""
    for env_var, (section, key) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value:
            if section not in raw_config:
                raw_config[section] = {}
            raw_config[section][key] = value
    return raw_config


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load and validate configuration from a YAML file.

    Environment variables (loaded via dotenv) override YAML values when set.
    See _ENV_OVERRIDES for the mapping.

    Args:
        config_path: Path to the YAML config file. If None, uses the
            CONFIG_PATH environment variable or defaults to /app/config.yaml.

    Returns:
        Validated AppConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config file is invalid or missing required fields.
    """
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}. "
            f"Set CONFIG_PATH environment variable or provide --config argument."
        )

    logger.info("Loading configuration from %s", config_path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in configuration file: {e}") from e

    if not isinstance(raw_config, dict):
        raise ValueError(
            f"Configuration file must contain a YAML mapping, got: {type(raw_config).__name__}"
        )

    raw_config = _apply_env_overrides(raw_config)

    try:
        config = AppConfig(**raw_config)
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}") from e

    logger.info(
        "Configuration loaded successfully for client: %s",
        config.client.name,
    )

    return config
