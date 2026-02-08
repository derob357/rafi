"""Extract client configuration from an interview transcript using OpenAI.

Reads a transcript of an onboarding interview, sends it to an LLM with
a structured extraction prompt, parses the response into a config YAML
file matching the rafi_assistant schema, and validates the result with
pydantic. Prompts the operator for any missing required fields.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# Maximum transcript length sent to the LLM (characters)
MAX_TRANSCRIPT_LENGTH = 100_000


# ---------------------------------------------------------------------------
# Pydantic models for extracted config validation
# ---------------------------------------------------------------------------


class ClientInfo(BaseModel):
    """Client identity information extracted from the interview."""

    name: str = Field(..., min_length=1, description="Client full name")
    company: str = Field(default="", description="Company or organization name")


class SettingsInfo(BaseModel):
    """Operational settings extracted from the interview."""

    morning_briefing_time: str = Field(
        default="08:00", description="Morning briefing time in HH:MM"
    )
    quiet_hours_start: str = Field(
        default="22:00", description="Quiet hours start in HH:MM"
    )
    quiet_hours_end: str = Field(
        default="07:00", description="Quiet hours end in HH:MM"
    )
    reminder_lead_minutes: int = Field(
        default=15, ge=1, le=1440, description="Minutes before event for reminder"
    )
    min_snooze_minutes: int = Field(
        default=5, ge=1, le=1440, description="Minimum snooze duration in minutes"
    )
    timezone: str = Field(
        default="America/New_York", description="Client timezone (IANA)"
    )

    @field_validator("morning_briefing_time", "quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """Ensure time values are in HH:MM format."""
        v = v.strip()
        if len(v) != 5 or v[2] != ":":
            raise ValueError(f"Time must be in HH:MM format, got '{v}'")
        try:
            hour, minute = int(v[:2]), int(v[3:])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            raise ValueError(f"Invalid time value: '{v}'")
        return v


class AssistantInfo(BaseModel):
    """Assistant personality and voice preferences."""

    agent_name: str = Field(default="Rafi", description="Name the assistant uses")
    personality: str = Field(
        default="Professional, friendly, concise",
        description="Personality/style instructions",
    )
    voice_preference: str = Field(
        default="", description="Preferred voice description or ElevenLabs voice ID"
    )


class ContactInfo(BaseModel):
    """Client contact information."""

    phone_number: str = Field(default="", description="Client phone number")
    email: str = Field(default="", description="Client email address")


class ExtractedConfig(BaseModel):
    """Complete extracted configuration from an onboarding interview."""

    client: ClientInfo
    assistant: AssistantInfo = Field(default_factory=AssistantInfo)
    contact: ContactInfo = Field(default_factory=ContactInfo)
    settings: SettingsInfo = Field(default_factory=SettingsInfo)
    special_instructions: str = Field(
        default="", description="Any additional instructions from the client"
    )


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are a configuration extraction assistant for the Rafi AI assistant platform.
Your task is to extract client details from an onboarding interview transcript.

Extract the following information and return it as a JSON object:

{
  "client": {
    "name": "Full name of the client",
    "company": "Company or organization (empty string if not mentioned)"
  },
  "assistant": {
    "agent_name": "What the client wants their assistant to be called (default: Rafi)",
    "personality": "Personality/style description the client prefers (default: Professional, friendly, concise)",
    "voice_preference": "Any voice preference mentioned (male/female, accent, specific description)"
  },
  "contact": {
    "phone_number": "Client phone number in +E.164 format if mentioned",
    "email": "Client email address if mentioned"
  },
  "settings": {
    "morning_briefing_time": "Preferred time for morning briefing in HH:MM 24-hour format (default: 08:00)",
    "quiet_hours_start": "When to stop calls in HH:MM 24-hour format (default: 22:00)",
    "quiet_hours_end": "When calls can resume in HH:MM 24-hour format (default: 07:00)",
    "reminder_lead_minutes": "How many minutes before events to remind (default: 15)",
    "min_snooze_minutes": "Minimum snooze duration in minutes (default: 5)",
    "timezone": "Client timezone in IANA format (default: America/New_York)"
  },
  "special_instructions": "Any special requirements or instructions the client mentioned"
}

Rules:
- Extract ONLY what is explicitly stated or clearly implied in the transcript.
- Use the specified defaults for any field not mentioned.
- For phone numbers, convert to +E.164 format (e.g., +12125551234).
- For times, use 24-hour HH:MM format.
- For timezone, use IANA format (e.g., America/New_York, Europe/London).
- Return ONLY the JSON object, no other text.
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


class ConfigExtractionError(Exception):
    """Raised when config extraction fails."""

    pass


def _get_openai_client() -> OpenAI:
    """Create and return an OpenAI client.

    Returns:
        Configured OpenAI client.

    Raises:
        ConfigExtractionError: If the API key is not set.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ConfigExtractionError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before running config extraction."
        )
    return OpenAI(api_key=api_key)


def _read_transcript(transcript_path: Path) -> str:
    """Read and validate a transcript file.

    Args:
        transcript_path: Path to the transcript text file.

    Returns:
        The transcript text.

    Raises:
        ConfigExtractionError: If the file cannot be read or is empty.
    """
    if not transcript_path.exists():
        raise ConfigExtractionError(
            f"Transcript file not found: {transcript_path}"
        )

    if not transcript_path.is_file():
        raise ConfigExtractionError(
            f"Path is not a file: {transcript_path}"
        )

    try:
        text = transcript_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigExtractionError(
            f"Failed to read transcript file: {exc}"
        ) from exc

    text = text.strip()
    if not text:
        raise ConfigExtractionError("Transcript file is empty")

    if len(text) > MAX_TRANSCRIPT_LENGTH:
        logger.warning(
            "Transcript is %d chars, truncating to %d",
            len(text),
            MAX_TRANSCRIPT_LENGTH,
        )
        text = text[:MAX_TRANSCRIPT_LENGTH]

    return text


def _call_llm(client: OpenAI, transcript: str) -> dict[str, Any]:
    """Send the transcript to OpenAI and parse the extracted config.

    Args:
        client: Configured OpenAI client.
        transcript: The interview transcript text.

    Returns:
        Parsed JSON dictionary with extracted config fields.

    Raises:
        ConfigExtractionError: If the LLM call fails or the response
            cannot be parsed.
    """
    logger.info("Sending transcript to LLM for extraction (%d chars)", len(transcript))

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract the client configuration from the following "
                        "onboarding interview transcript:\n\n"
                        f"---\n{transcript}\n---"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise ConfigExtractionError(
            f"OpenAI API call failed: {exc}"
        ) from exc

    content = response.choices[0].message.content
    if not content:
        raise ConfigExtractionError("LLM returned an empty response")

    # Parse JSON from the response
    try:
        extracted = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ConfigExtractionError(
            f"LLM response is not valid JSON: {exc}\nResponse: {content[:500]}"
        ) from exc

    if not isinstance(extracted, dict):
        raise ConfigExtractionError(
            f"LLM response is not a JSON object: {type(extracted)}"
        )

    logger.info("LLM extraction complete")
    return extracted


def _validate_extracted(data: dict[str, Any]) -> ExtractedConfig:
    """Validate the extracted data against the pydantic model.

    Args:
        data: Raw extracted dictionary from the LLM.

    Returns:
        Validated ExtractedConfig instance.

    Raises:
        ConfigExtractionError: If validation fails.
    """
    try:
        return ExtractedConfig(**data)
    except ValidationError as exc:
        raise ConfigExtractionError(
            f"Extracted config validation failed:\n{exc}"
        ) from exc


def _prompt_for_missing_fields(config: ExtractedConfig) -> ExtractedConfig:
    """Interactively prompt the operator for any missing required fields.

    Checks critical fields and asks the operator to provide values
    for any that are empty or set to defaults that likely need updating.

    Args:
        config: The current extracted configuration.

    Returns:
        Updated configuration with operator-provided values.
    """
    data = config.model_dump()

    # Check for missing client name (should not happen but safety check)
    if not data["client"]["name"] or data["client"]["name"] == "Unknown":
        value = input("Client name was not found in transcript. Enter client name: ").strip()
        if value:
            data["client"]["name"] = value

    # Check for missing phone number
    if not data["contact"]["phone_number"]:
        value = input(
            "Client phone number was not found. Enter phone (+E.164 format, or press Enter to skip): "
        ).strip()
        if value:
            data["contact"]["phone_number"] = value

    # Check for missing email
    if not data["contact"]["email"]:
        value = input(
            "Client email was not found. Enter email (or press Enter to skip): "
        ).strip()
        if value:
            data["contact"]["email"] = value

    try:
        return ExtractedConfig(**data)
    except ValidationError:
        logger.warning("Validation failed after prompting; using original values")
        return config


def _build_config_yaml(config: ExtractedConfig) -> dict[str, Any]:
    """Build the full client config YAML structure from extracted config.

    Merges extracted values into the template config structure, leaving
    API keys and credentials as placeholders for manual entry.

    Args:
        config: Validated extracted configuration.

    Returns:
        Complete config dictionary ready for YAML serialization.
    """
    return {
        "client": {
            "name": config.client.name,
            "company": config.client.company,
        },
        "telegram": {
            "bot_token": "BOT_TOKEN_HERE",
            "user_id": 0,
        },
        "twilio": {
            "account_sid": "AC_PLACEHOLDER",
            "auth_token": "PLACEHOLDER",
            "phone_number": "",
            "client_phone": config.contact.phone_number,
        },
        "elevenlabs": {
            "api_key": "PLACEHOLDER",
            "voice_id": config.assistant.voice_preference or "PLACEHOLDER",
            "agent_name": config.assistant.agent_name,
            "personality": config.assistant.personality,
        },
        "llm": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "PLACEHOLDER",
        },
        "google": {
            "client_id": "PLACEHOLDER",
            "client_secret": "PLACEHOLDER",
            "refresh_token": "",
        },
        "supabase": {
            "url": "",
            "anon_key": "",
            "service_role_key": "",
        },
        "deepgram": {
            "api_key": "PLACEHOLDER",
        },
        "weather": {
            "api_key": "PLACEHOLDER",
        },
        "settings": {
            "morning_briefing_time": config.settings.morning_briefing_time,
            "quiet_hours_start": config.settings.quiet_hours_start,
            "quiet_hours_end": config.settings.quiet_hours_end,
            "reminder_lead_minutes": config.settings.reminder_lead_minutes,
            "min_snooze_minutes": config.settings.min_snooze_minutes,
            "save_to_disk": False,
            "timezone": config.settings.timezone,
        },
    }


def _save_config_yaml(config_dict: dict[str, Any], output_path: Path) -> None:
    """Write the config dictionary to a YAML file.

    Args:
        config_dict: The config dictionary to serialize.
        output_path: Path where the YAML file will be written.

    Raises:
        ConfigExtractionError: If the file cannot be written.
    """
    try:
        header = (
            "# Rafi Assistant Client Configuration\n"
            "# Generated by rafi-deploy config extractor\n"
            "# REVIEW ALL VALUES before deploying.\n"
            "# Replace all PLACEHOLDER values with real credentials.\n"
            "# Fields marked with empty strings will be auto-filled by deploy.\n"
            "\n"
        )
        yaml_content = yaml.dump(
            config_dict,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        output_path.write_text(header + yaml_content, encoding="utf-8")
        logger.info("Config saved to: %s", output_path)
    except OSError as exc:
        raise ConfigExtractionError(
            f"Failed to write config file: {exc}"
        ) from exc


def extract_config(
    transcript_path: str | Path,
    output_path: str | Path,
    interactive: bool = True,
) -> Path:
    """Extract client config from an interview transcript and save as YAML.

    This is the main entry point for config extraction. It reads the
    transcript, sends it to the LLM, validates the response, optionally
    prompts for missing fields, and writes the final config YAML.

    Args:
        transcript_path: Path to the transcript text file.
        output_path: Path where the config YAML will be saved.
        interactive: If True, prompt for missing fields interactively.
            Defaults to True.

    Returns:
        Resolved Path to the saved config YAML file.

    Raises:
        ConfigExtractionError: If any step in the extraction pipeline fails.
    """
    transcript_path = Path(transcript_path).resolve()
    output_path = Path(output_path).resolve()

    if not output_path.parent.exists():
        raise ConfigExtractionError(
            f"Output directory does not exist: {output_path.parent}"
        )

    # Step 1: Read transcript
    transcript = _read_transcript(transcript_path)
    logger.info("Read transcript: %d characters", len(transcript))

    # Step 2: Call LLM for extraction
    openai_client = _get_openai_client()
    extracted_data = _call_llm(openai_client, transcript)

    # Step 3: Validate with pydantic
    validated_config = _validate_extracted(extracted_data)
    logger.info("Extracted config for client: %s", validated_config.client.name)

    # Step 4: Prompt for missing fields (if interactive)
    if interactive:
        validated_config = _prompt_for_missing_fields(validated_config)

    # Step 5: Build full config YAML
    config_dict = _build_config_yaml(validated_config)

    # Step 6: Save to file
    _save_config_yaml(config_dict, output_path)

    print(f"\nConfig extracted and saved to: {output_path}")
    print("Please review the file and replace all PLACEHOLDER values.")
    print("Remember to create a Telegram bot via BotFather and add the token.")

    return output_path
