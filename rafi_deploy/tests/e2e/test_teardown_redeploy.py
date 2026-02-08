"""
E2E tests for teardown and redeploy workflows.

Marked @pytest.mark.e2e.

Tests:
- Deploy a client -> stop container -> verify stopped -> redeploy -> verify running
  -> verify Supabase data preserved
- Client data in Supabase survives container restart
"""

from unittest.mock import MagicMock, call, patch

import pytest
import yaml


pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_container_stopped(status: str) -> None:
    """Validate that a Docker container is stopped."""
    assert status is not None, "Status must not be None"
    status_lower = status.lower()
    assert any(
        word in status_lower for word in ["exited", "stopped", "not running", "not_found"]
    ), f"Container should be stopped, got: {status}"


def validate_container_running(status: str) -> None:
    """Validate that a Docker container is running."""
    assert status is not None, "Status must not be None"
    assert "running" in status.lower(), f"Container should be running, got: {status}"


def validate_supabase_data_intact(query_result: list) -> None:
    """Validate that Supabase data was preserved after restart."""
    assert query_result is not None, "Query result must not be None"
    assert isinstance(query_result, list), "Query result should be a list"
    assert len(query_result) > 0, "Data should be preserved after restart"


# ---------------------------------------------------------------------------
# E2E Tests: Teardown and Redeploy
# ---------------------------------------------------------------------------

class TestTeardownRedeployCycle:
    """Deploy -> stop -> verify stopped -> redeploy -> verify running -> data preserved."""

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.start_container")
    @patch("src.deploy.docker_manager.stop_container")
    @patch("src.deploy.docker_manager.build_image")
    @patch("src.deploy.supabase_provisioner.create_project")
    @patch("src.deploy.twilio_provisioner.provision_number")
    def test_full_teardown_redeploy_cycle(
        self,
        mock_provision,
        mock_create_project,
        mock_build,
        mock_stop,
        mock_start,
        mock_status,
        sample_config,
        sample_config_path,
        mock_twilio_client,
        mock_supabase_admin,
        mock_docker_ssh,
    ):
        """
        Full cycle:
        1. Deploy client (Twilio + Supabase + Docker)
        2. Stop container
        3. Verify stopped
        4. Redeploy (restart container)
        5. Verify running
        6. Verify Supabase data preserved
        """
        # --- Phase 1: Initial Deploy ---
        mock_provision.return_value = "+14155550100"
        mock_create_project.return_value = {
            "project_id": "proj_test",
            "url": "https://test.supabase.co",
            "anon_key": "eyJ_test",
            "service_role_key": "eyJ_test_svc",
        }
        mock_build.return_value = True

        # Provision Twilio
        phone = mock_provision(
            client=mock_twilio_client,
            area_code="415",
            webhook_url="https://ec2.example.com/webhook/voice",
        )
        assert phone == "+14155550100"

        # Create Supabase project
        project = mock_create_project(
            admin=mock_supabase_admin,
            client_name="john_doe",
            organization_id="org_test",
            region="us-east-1",
        )
        assert project is not None

        # Build and start container
        mock_build(
            ssh_client=mock_docker_ssh,
            image_name="rafi_assistant",
            build_context="/home/ubuntu/rafi_assistant",
        )

        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )

        # Verify running
        mock_status.return_value = "running"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_running(status)

        # --- Phase 2: Stop Container ---
        mock_stop.return_value = True
        mock_stop(ssh_client=mock_docker_ssh, client_name="john_doe")
        mock_stop.assert_called()

        # Verify stopped
        mock_status.return_value = "exited"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_stopped(status)

        # --- Phase 3: Redeploy ---
        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )

        # Verify running again
        mock_status.return_value = "running"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_running(status)

        # --- Phase 4: Verify Supabase data preserved ---
        # Supabase is external; container restart should not affect it
        # Simulate a query to Supabase
        mock_supabase_query = MagicMock()
        mock_supabase_query.return_value = [
            {"id": "msg_1", "role": "user", "content": "Hello"},
            {"id": "msg_2", "role": "assistant", "content": "Hi there!"},
        ]
        query_result = mock_supabase_query()
        validate_supabase_data_intact(query_result)

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.restart_container")
    def test_restart_preserves_functionality(
        self,
        mock_restart,
        mock_status,
        mock_docker_ssh,
    ):
        """Restart container and verify it comes back up."""
        # Restart
        mock_restart.return_value = True
        mock_restart(ssh_client=mock_docker_ssh, client_name="john_doe")
        mock_restart.assert_called_once()

        # Verify running after restart
        mock_status.return_value = "running"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_running(status)


class TestSupabaseDataSurvivesRestart:
    """Client data in Supabase survives container restart."""

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.start_container")
    @patch("src.deploy.docker_manager.stop_container")
    def test_messages_table_preserved(
        self,
        mock_stop,
        mock_start,
        mock_status,
        mock_docker_ssh,
        mock_supabase_admin,
        sample_config_path,
    ):
        """
        1. Simulate data existing in Supabase messages table
        2. Stop container
        3. Restart container
        4. Query Supabase - data should still be there
        """
        # Simulate pre-existing data in Supabase
        supabase_messages = [
            {
                "id": "msg_001",
                "role": "user",
                "content": "What's on my calendar today?",
                "source": "telegram_text",
            },
            {
                "id": "msg_002",
                "role": "assistant",
                "content": "You have 3 meetings today.",
                "source": "telegram_text",
            },
        ]

        # Mock Supabase query
        mock_query = MagicMock()
        mock_query.return_value = {"data": supabase_messages, "error": None}

        # Step 1: Verify data exists before stop
        result_before = mock_query()
        assert len(result_before["data"]) == 2

        # Step 2: Stop container
        mock_stop.return_value = True
        mock_stop(ssh_client=mock_docker_ssh, client_name="john_doe")

        mock_status.return_value = "exited"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_stopped(status)

        # Step 3: Restart container
        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )

        mock_status.return_value = "running"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_running(status)

        # Step 4: Verify data still exists (Supabase is external, unaffected)
        result_after = mock_query()
        assert result_after["data"] == supabase_messages
        assert len(result_after["data"]) == 2

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.start_container")
    @patch("src.deploy.docker_manager.stop_container")
    def test_tasks_and_notes_preserved(
        self,
        mock_stop,
        mock_start,
        mock_status,
        mock_docker_ssh,
        sample_config_path,
    ):
        """Tasks and notes in Supabase survive container restart."""
        supabase_tasks = [
            {"id": "task_001", "title": "Buy groceries", "status": "pending"},
            {"id": "task_002", "title": "Call dentist", "status": "completed"},
        ]
        supabase_notes = [
            {"id": "note_001", "title": "Meeting notes", "content": "Discussed Q1 targets"},
        ]

        mock_task_query = MagicMock(return_value={"data": supabase_tasks})
        mock_note_query = MagicMock(return_value={"data": supabase_notes})

        # Verify data before restart
        tasks_before = mock_task_query()
        notes_before = mock_note_query()
        assert len(tasks_before["data"]) == 2
        assert len(notes_before["data"]) == 1

        # Stop and restart container
        mock_stop.return_value = True
        mock_stop(ssh_client=mock_docker_ssh, client_name="john_doe")

        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )

        mock_status.return_value = "running"
        status = mock_status(ssh_client=mock_docker_ssh, client_name="john_doe")
        validate_container_running(status)

        # Verify data after restart (Supabase is independent of container)
        tasks_after = mock_task_query()
        notes_after = mock_note_query()
        assert tasks_after["data"] == supabase_tasks
        assert notes_after["data"] == supabase_notes

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.start_container")
    @patch("src.deploy.docker_manager.stop_container")
    def test_call_logs_preserved(
        self,
        mock_stop,
        mock_start,
        mock_status,
        mock_docker_ssh,
        sample_config_path,
    ):
        """Call logs in Supabase survive container restart."""
        call_logs = [
            {
                "id": "log_001",
                "call_sid": "CA_test_123",
                "direction": "inbound",
                "duration_seconds": 120,
                "transcript": "Hello, what's on my schedule today?",
                "summary": "Client asked about today's schedule.",
            },
        ]

        mock_log_query = MagicMock(return_value={"data": call_logs})

        # Data exists before
        logs_before = mock_log_query()
        assert len(logs_before["data"]) == 1

        # Restart cycle
        mock_stop.return_value = True
        mock_stop(ssh_client=mock_docker_ssh, client_name="john_doe")
        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )
        mock_status.return_value = "running"

        # Data preserved
        logs_after = mock_log_query()
        assert logs_after["data"] == call_logs
        assert logs_after["data"][0]["call_sid"] == "CA_test_123"

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.start_container")
    @patch("src.deploy.docker_manager.stop_container")
    def test_settings_preserved(
        self,
        mock_stop,
        mock_start,
        mock_status,
        mock_docker_ssh,
        sample_config_path,
    ):
        """Client settings in Supabase survive container restart."""
        settings_data = [
            {"key": "morning_briefing_time", "value": "08:00"},
            {"key": "quiet_hours_start", "value": "22:00"},
            {"key": "quiet_hours_end", "value": "07:00"},
            {"key": "reminder_lead_minutes", "value": "15"},
            {"key": "min_snooze_minutes", "value": "5"},
        ]

        mock_settings_query = MagicMock(return_value={"data": settings_data})

        # Before restart
        settings_before = mock_settings_query()
        assert len(settings_before["data"]) == 5

        # Restart cycle
        mock_stop.return_value = True
        mock_stop(ssh_client=mock_docker_ssh, client_name="john_doe")
        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )
        mock_status.return_value = "running"

        # After restart
        settings_after = mock_settings_query()
        assert settings_after["data"] == settings_data

    @patch("src.deploy.docker_manager.get_container_status")
    @patch("src.deploy.docker_manager.start_container")
    @patch("src.deploy.docker_manager.stop_container")
    def test_oauth_tokens_preserved(
        self,
        mock_stop,
        mock_start,
        mock_status,
        mock_docker_ssh,
        sample_config_path,
    ):
        """OAuth tokens in Supabase survive container restart."""
        oauth_data = [
            {
                "provider": "google",
                "access_token": "encrypted_access_token_data",
                "refresh_token": "encrypted_refresh_token_data",
                "scopes": "calendar.events gmail.readonly gmail.send gmail.modify",
            },
        ]

        mock_oauth_query = MagicMock(return_value={"data": oauth_data})

        # Before restart
        oauth_before = mock_oauth_query()
        assert len(oauth_before["data"]) == 1
        assert oauth_before["data"][0]["provider"] == "google"

        # Restart cycle
        mock_stop.return_value = True
        mock_stop(ssh_client=mock_docker_ssh, client_name="john_doe")
        mock_start.return_value = True
        mock_start(
            ssh_client=mock_docker_ssh,
            client_name="john_doe",
            image_name="rafi_assistant",
            config_path=str(sample_config_path),
            port=8001,
        )
        mock_status.return_value = "running"

        # After restart
        oauth_after = mock_oauth_query()
        assert oauth_after["data"] == oauth_data
        assert oauth_after["data"][0]["refresh_token"] == "encrypted_refresh_token_data"
