"""Shared pytest fixtures for the rafi_assistant test suite.

Provides mock clients, sample data objects, and a valid test configuration
that all test modules can reuse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Attempt to import the real Pydantic config models from source.  If the
# source code has not been written yet, fall back to building a plain dict
# so tests can still express intent and be adapted later.
# ---------------------------------------------------------------------------
try:
    from src.config.loader import (
        AppConfig,
        ClientConfig,
        DeepgramConfig,
        ElevenLabsConfig,
        GoogleConfig,
        LLMConfig,
        SettingsConfig,
        SupabaseConfig,
        TelegramConfig,
        TwilioConfig,
        WeatherConfig,
    )

    _HAS_CONFIG = True
except ImportError:
    _HAS_CONFIG = False


# ---------------------------------------------------------------------------
# Valid test configuration values
# ---------------------------------------------------------------------------
_TEST_CONFIG_DICT: Dict[str, Any] = {
    "client": {
        "name": "Test User",
        "company": "Test Corp",
    },
    "telegram": {
        "bot_token": "123456789:ABCdefGhIjKlMnOpQrStUvWxYz",
        "user_id": 987654321,
    },
    "twilio": {
        "account_sid": "ACtest1234567890abcdef1234567890ab",
        "auth_token": "test_auth_token_value",
        "phone_number": "+15551234567",
        "client_phone": "+15559876543",
    },
    "elevenlabs": {
        "api_key": "el_test_api_key_123",
        "voice_id": "voice_test_id_456",
        "agent_name": "TestRafi",
        "personality": "Professional, friendly, concise",
    },
    "llm": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "sk-test-key-1234567890abcdef",
        "embedding_model": "text-embedding-3-large",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "google": {
        "client_id": "google_client_id_test.apps.googleusercontent.com",
        "client_secret": "google_client_secret_test",
        "refresh_token": "google_refresh_token_test",
    },
    "supabase": {
        "url": "https://testproject.supabase.co",
        "anon_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_anon",
        "service_role_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_service",
    },
    "deepgram": {
        "api_key": "dg_test_api_key_789",
    },
    "weather": {
        "api_key": "weather_test_api_key_abc",
    },
    "settings": {
        "morning_briefing_time": "08:00",
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "reminder_lead_minutes": 15,
        "min_snooze_minutes": 5,
        "save_to_disk": False,
        "timezone": "America/New_York",
    },
}


# ---------------------------------------------------------------------------
# Fixtures: Configuration
# ---------------------------------------------------------------------------


@pytest.fixture
def test_config_dict() -> Dict[str, Any]:
    """Return a plain dict with valid test config values.

    Useful when you need to manipulate raw config data before validation.
    """
    import copy

    return copy.deepcopy(_TEST_CONFIG_DICT)


@pytest.fixture
def mock_config(test_config_dict: Dict[str, Any]):
    """Return a validated AppConfig (Pydantic model) with test values.

    If the real AppConfig is not importable (source not yet written), returns
    a MagicMock with the same nested attribute access pattern.
    """
    if _HAS_CONFIG:
        return AppConfig(**test_config_dict)

    # Fallback: build a mock that mirrors attribute access
    cfg = MagicMock(name="AppConfig")
    cfg.client.name = test_config_dict["client"]["name"]
    cfg.client.company = test_config_dict["client"]["company"]
    cfg.telegram.bot_token = test_config_dict["telegram"]["bot_token"]
    cfg.telegram.user_id = test_config_dict["telegram"]["user_id"]
    cfg.twilio.account_sid = test_config_dict["twilio"]["account_sid"]
    cfg.twilio.auth_token = test_config_dict["twilio"]["auth_token"]
    cfg.twilio.phone_number = test_config_dict["twilio"]["phone_number"]
    cfg.twilio.client_phone = test_config_dict["twilio"]["client_phone"]
    cfg.elevenlabs.api_key = test_config_dict["elevenlabs"]["api_key"]
    cfg.elevenlabs.voice_id = test_config_dict["elevenlabs"]["voice_id"]
    cfg.elevenlabs.agent_name = test_config_dict["elevenlabs"]["agent_name"]
    cfg.elevenlabs.personality = test_config_dict["elevenlabs"]["personality"]
    cfg.llm.provider = test_config_dict["llm"]["provider"]
    cfg.llm.model = test_config_dict["llm"]["model"]
    cfg.llm.api_key = test_config_dict["llm"]["api_key"]
    cfg.google.client_id = test_config_dict["google"]["client_id"]
    cfg.google.client_secret = test_config_dict["google"]["client_secret"]
    cfg.google.refresh_token = test_config_dict["google"]["refresh_token"]
    cfg.supabase.url = test_config_dict["supabase"]["url"]
    cfg.supabase.anon_key = test_config_dict["supabase"]["anon_key"]
    cfg.supabase.service_role_key = test_config_dict["supabase"]["service_role_key"]
    cfg.deepgram.api_key = test_config_dict["deepgram"]["api_key"]
    cfg.weather.api_key = test_config_dict["weather"]["api_key"]
    cfg.settings.morning_briefing_time = test_config_dict["settings"]["morning_briefing_time"]
    cfg.settings.quiet_hours_start = test_config_dict["settings"]["quiet_hours_start"]
    cfg.settings.quiet_hours_end = test_config_dict["settings"]["quiet_hours_end"]
    cfg.settings.reminder_lead_minutes = test_config_dict["settings"]["reminder_lead_minutes"]
    cfg.settings.min_snooze_minutes = test_config_dict["settings"]["min_snooze_minutes"]
    cfg.settings.save_to_disk = test_config_dict["settings"]["save_to_disk"]
    cfg.settings.timezone = test_config_dict["settings"]["timezone"]
    return cfg


# ---------------------------------------------------------------------------
# Fixtures: External clients (mocked)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_supabase() -> MagicMock:
    """Return a mocked Supabase client.

    Provides `.table().select()`, `.table().insert()`, `.table().update()`,
    `.table().delete()` chains, plus `.rpc()` for pgvector searches.
    """
    client = MagicMock(name="SupabaseClient")

    # Build a chainable table mock
    table_mock = MagicMock(name="Table")
    table_mock.select.return_value = table_mock
    table_mock.insert.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.delete.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.neq.return_value = table_mock
    table_mock.order.return_value = table_mock
    table_mock.limit.return_value = table_mock
    table_mock.single.return_value = table_mock
    table_mock.execute.return_value = AsyncMock(return_value=MagicMock(data=[], count=0))

    client.table.return_value = table_mock
    client.insert = table_mock.insert
    client.select = table_mock.select
    client.update = table_mock.update
    client.delete = table_mock.delete
    client.rpc.return_value = AsyncMock(return_value=MagicMock(data=[], count=0))
    client.upsert = AsyncMock(return_value=MagicMock(data=[], count=0))
    client.embedding_search = AsyncMock(return_value=[])

    return client


@pytest.fixture
def mock_openai() -> MagicMock:
    """Return a mocked OpenAI client.

    Provides `.chat.completions.create()` and `.embeddings.create()`.
    """
    client = MagicMock(name="OpenAIClient")

    # Chat completion mock
    choice = MagicMock()
    choice.message.content = "This is a test response from the LLM."
    choice.message.tool_calls = None
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage.prompt_tokens = 100
    completion.usage.completion_tokens = 50
    client.chat.completions.create.return_value = completion

    # Embedding mock
    embedding_data = MagicMock()
    embedding_data.embedding = [0.01] * 3072  # text-embedding-3-large dimension
    embedding_response = MagicMock()
    embedding_response.data = [embedding_data]
    client.embeddings.create.return_value = embedding_response

    return client


@pytest.fixture
def mock_twilio() -> MagicMock:
    """Return a mocked Twilio client.

    Provides `.calls.create()`, `.messages.create()`, and request validation.
    """
    client = MagicMock(name="TwilioClient")

    call_mock = MagicMock()
    call_mock.sid = "CA1234567890abcdef1234567890abcdef"
    call_mock.status = "queued"
    client.calls.create.return_value = call_mock

    message_mock = MagicMock()
    message_mock.sid = "SM1234567890abcdef1234567890abcdef"
    message_mock.status = "sent"
    client.messages.create.return_value = message_mock

    return client


# ---------------------------------------------------------------------------
# Fixtures: Sample data objects
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_calendar_event() -> Dict[str, Any]:
    """Return a dict representing a typical Google Calendar event."""
    return {
        "id": "evt_abc123def456",
        "summary": "Team Standup",
        "description": "Daily standup meeting with the engineering team.",
        "location": "Conference Room B",
        "start": {
            "dateTime": "2025-06-15T09:00:00-04:00",
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": "2025-06-15T09:30:00-04:00",
            "timeZone": "America/New_York",
        },
        "status": "confirmed",
        "organizer": {
            "email": "organizer@example.com",
            "displayName": "Team Lead",
        },
        "attendees": [
            {"email": "user@example.com", "responseStatus": "accepted"},
            {"email": "colleague@example.com", "responseStatus": "needsAction"},
        ],
        "reminders": {
            "useDefault": True,
        },
        "htmlLink": "https://calendar.google.com/calendar/event?eid=abc123",
        "created": "2025-06-01T12:00:00.000Z",
        "updated": "2025-06-01T12:00:00.000Z",
    }


@pytest.fixture
def sample_email() -> Dict[str, Any]:
    """Return a dict representing a typical Gmail message."""
    return {
        "id": "msg_18a1b2c3d4e5f6",
        "threadId": "thread_18a1b2c3d4e5f6",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hi, just wanted to follow up on our meeting...",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "testuser@example.com"},
                {"name": "Subject", "value": "Follow-up: Project Discussion"},
                {"name": "Date", "value": "Sun, 15 Jun 2025 10:30:00 -0400"},
            ],
            "body": {
                "data": "SGksIGp1c3Qgd2FudGVkIHRvIGZvbGxvdyB1cCBvbiBvdXIgbWVldGluZy4=",
            },
        },
        "sizeEstimate": 2048,
        "internalDate": "1718451000000",
    }


@pytest.fixture
def sample_task() -> Dict[str, Any]:
    """Return a dict representing a typical task record from Supabase."""
    return {
        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "title": "Review quarterly report",
        "description": "Go through the Q2 financials and prepare summary notes.",
        "status": "pending",
        "due_date": "2025-06-20T17:00:00+00:00",
        "created_at": "2025-06-10T09:00:00+00:00",
        "updated_at": "2025-06-10T09:00:00+00:00",
    }


@pytest.fixture
def sample_note() -> Dict[str, Any]:
    """Return a dict representing a typical note record from Supabase."""
    return {
        "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "title": "Meeting Notes - Product Sync",
        "content": "Discussed roadmap for Q3. Key decisions: 1) Launch feature X by July. 2) Hire two more engineers.",
        "created_at": "2025-06-12T14:30:00+00:00",
        "updated_at": "2025-06-12T14:30:00+00:00",
    }


# ---------------------------------------------------------------------------
# Fixtures: Utility helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_yaml_config(tmp_path, test_config_dict) -> str:
    """Write test config dict to a temporary YAML file and return its path."""
    import yaml

    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(test_config_dict, f)
    return str(config_file)
