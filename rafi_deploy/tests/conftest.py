"""
Shared pytest fixtures for rafi_deploy tests.

Provides common fixtures used across unit, integration, security, and e2e tests:
- sample_transcript: realistic interview transcript string
- sample_config: valid client config dict matching the YAML schema
- sample_config_path: writes sample config to a temp file, returns path
- mock_twilio_client: mocked Twilio REST client
- mock_supabase_admin: mocked Supabase management API client
- mock_docker_ssh: mocked paramiko SSH client for Docker operations
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# sample_transcript
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_transcript() -> str:
    """Return a realistic onboarding interview transcript string."""
    return (
        "Interviewer: Thanks for joining, let's get you set up with Rafi. "
        "Can you start by telling me your full name?\n"
        "Client: Sure, my name is John Doe.\n"
        "Interviewer: Great, and what company are you with?\n"
        "Client: I'm at Acme Corp.\n"
        "Interviewer: What would you like to call your assistant?\n"
        "Client: Let's go with Rafi, that sounds good.\n"
        "Interviewer: And what personality should the assistant have?\n"
        "Client: Professional, friendly, and concise. I like things to the point.\n"
        "Interviewer: Got it. What's your phone number?\n"
        "Client: It's plus one four one five five five five one two three four.\n"
        "Interviewer: And your Google account email for calendar and email access?\n"
        "Client: john.doe@gmail.com\n"
        "Interviewer: What time would you like your morning briefing call?\n"
        "Client: Eight AM works for me.\n"
        "Interviewer: What about quiet hours, when should the assistant not call you?\n"
        "Client: No calls between ten PM and seven AM.\n"
        "Interviewer: How many minutes before a meeting should you get a reminder?\n"
        "Client: Fifteen minutes is perfect.\n"
        "Interviewer: And minimum snooze duration?\n"
        "Client: Five minutes.\n"
        "Interviewer: What timezone are you in?\n"
        "Client: Eastern time, America/New_York.\n"
        "Interviewer: Any special instructions for your assistant?\n"
        "Client: Always address me as Mr. Doe in formal settings, "
        "and use my first name otherwise.\n"
        "Interviewer: Great, that covers everything. We'll have your assistant "
        "set up shortly!"
    )


# ---------------------------------------------------------------------------
# sample_config
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_config() -> dict:
    """Return a valid client config dict matching the rafi_assistant YAML schema."""
    return {
        "client": {
            "name": "John Doe",
            "company": "Acme Corp",
        },
        "telegram": {
            "bot_token": "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            "user_id": 123456789,
        },
        "twilio": {
            "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "auth_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "phone_number": "+14155551234",
            "client_phone": "+14155559876",
        },
        "elevenlabs": {
            "api_key": "el_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "voice_id": "voice_abc123",
            "agent_name": "Rafi",
            "personality": "Professional, friendly, concise",
        },
        "llm": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        },
        "google": {
            "client_id": "123456789-abcdefg.apps.googleusercontent.com",
            "client_secret": "GOCSPX-xxxxxxxxxxxxxxxxxxxx",
            "refresh_token": "",
        },
        "supabase": {
            "url": "https://abcdefghijklmnop.supabase.co",
            "anon_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_anon_key",
            "service_role_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_svc_key",
        },
        "deepgram": {
            "api_key": "dg_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        },
        "weather": {
            "api_key": "weather_xxxxxxxxxxxxxxxxxxxxxxxx",
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
# sample_config_path
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_config_path(sample_config: dict, tmp_path: Path) -> Path:
    """Write the sample_config to a temporary YAML file and return its path."""
    config_file = tmp_path / "test_client_config.yaml"
    config_file.write_text(yaml.dump(sample_config, default_flow_style=False))
    return config_file


# ---------------------------------------------------------------------------
# mock_twilio_client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_twilio_client() -> MagicMock:
    """Return a mocked Twilio REST client with commonly used methods stubbed."""
    client = MagicMock()

    # Mock available phone numbers search
    available_number = MagicMock()
    available_number.phone_number = "+14155550100"
    available_number.friendly_name = "(415) 555-0100"
    available_number.capabilities = {
        "voice": True,
        "sms": True,
        "mms": True,
    }

    client.available_phone_numbers.return_value.local.list.return_value = [
        available_number,
    ]

    # Mock incoming phone number creation
    provisioned_number = MagicMock()
    provisioned_number.sid = "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    provisioned_number.phone_number = "+14155550100"
    provisioned_number.voice_url = "https://example.com/webhook/voice"
    provisioned_number.status = "in-use"
    client.incoming_phone_numbers.create.return_value = provisioned_number

    # Mock incoming phone number deletion (release)
    client.incoming_phone_numbers.return_value.delete.return_value = True

    # Mock phone number list for lookup
    client.incoming_phone_numbers.list.return_value = [provisioned_number]

    return client


# ---------------------------------------------------------------------------
# mock_supabase_admin
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase_admin() -> MagicMock:
    """Return a mocked Supabase management API client."""
    admin = MagicMock()

    # Mock project creation
    project = MagicMock()
    project.id = "proj_test_12345"
    project.name = "rafi-john-doe"
    project.organization_id = "org_test_67890"
    project.region = "us-east-1"
    project.status = "ACTIVE_HEALTHY"
    project.database = MagicMock()
    project.database.host = "db.abcdefghijklmnop.supabase.co"
    project.api_url = "https://abcdefghijklmnop.supabase.co"
    project.anon_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_anon"
    project.service_role_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_svc"
    admin.create_project.return_value = project

    # Mock SQL execution (for migrations)
    admin.execute_sql = MagicMock(return_value={"status": "ok"})

    # Mock project deletion
    admin.delete_project = MagicMock(return_value=True)

    # Mock project status check
    admin.get_project.return_value = project

    # Mock pgvector extension enable
    admin.enable_extension = MagicMock(return_value=True)

    return admin


# ---------------------------------------------------------------------------
# mock_docker_ssh
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_docker_ssh() -> MagicMock:
    """Return a mocked paramiko SSH client for Docker operations on EC2."""
    ssh = MagicMock()

    # Mock connect
    ssh.connect = MagicMock()

    # Helper to create mock exec responses
    def make_exec_result(stdout_text: str = "", stderr_text: str = "", exit_code: int = 0):
        stdin_mock = MagicMock()
        stdout_mock = MagicMock()
        stderr_mock = MagicMock()
        stdout_mock.read.return_value = stdout_text.encode("utf-8")
        stdout_mock.channel.recv_exit_status.return_value = exit_code
        stderr_mock.read.return_value = stderr_text.encode("utf-8")
        return stdin_mock, stdout_mock, stderr_mock

    # Default exec_command mock: returns success
    ssh.exec_command = MagicMock(
        return_value=make_exec_result("Container started successfully\n")
    )

    # Attach the helper so tests can override per-command
    ssh._make_exec_result = make_exec_result

    # Mock SFTP for file transfers
    sftp = MagicMock()
    sftp.put = MagicMock()
    sftp.get = MagicMock()
    sftp.stat = MagicMock()
    ssh.open_sftp.return_value = sftp

    # Mock close
    ssh.close = MagicMock()

    return ssh


# ---------------------------------------------------------------------------
# Additional helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_audio_bytes() -> bytes:
    """Return minimal WAV audio bytes for testing (silent, 0.1s, 16kHz mono)."""
    import struct

    sample_rate = 16000
    num_samples = 1600  # 0.1 seconds
    bits_per_sample = 16
    num_channels = 1
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    # WAV header
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    # Silent samples
    samples = b"\x00\x00" * num_samples
    return header + samples


@pytest.fixture
def sample_audio_path(sample_audio_bytes: bytes, tmp_path: Path) -> Path:
    """Write sample audio to a temporary WAV file and return its path."""
    audio_file = tmp_path / "test_interview.wav"
    audio_file.write_bytes(sample_audio_bytes)
    return audio_file


@pytest.fixture
def ec2_host_config() -> dict:
    """Return a sample EC2 SSH configuration dict."""
    return {
        "host": "ec2-test.example.com",
        "port": 22,
        "username": "ubuntu",
        "key_path": "/path/to/test_key.pem",
    }
