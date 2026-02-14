"""Unit tests for src/mcp/sse_transport.py — MCP SSE transport module.

Covers:
- Auth tests (verify_mcp_token):
  - No MCP_AUTH_TOKEN env var → passes through
  - Valid token → passes through
  - Invalid token → raises HTTPException 401
  - Missing Authorization header → raises HTTPException 401
  - Malformed header (no "Bearer " prefix) → raises HTTPException 401
- SessionManager tests:
  - create() returns session with valid UUID id
  - get() returns session and updates last_activity
  - get() returns None for unknown id
  - remove() removes session
  - Stale cleanup removes expired sessions (mock time)
  - Max capacity eviction removes oldest session
- LiveMCPServer tests:
  - rafi_get_calendar calls app_state.calendar.list_events()
  - rafi_get_feedback_summary queries app_state.db
  - rafi_send_message calls app_state.channel_manager.send_to_preferred()
  - Other tools fall through to parent MCPServer
- Route tests:
  - POST to /api/mcp/messages with unknown sessionId → 404
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from src.mcp.sse_transport import (
    LiveMCPServer,
    SessionManager,
    SSESession,
    verify_mcp_token,
)


# ===========================================================================
# Auth Tests — verify_mcp_token
# ===========================================================================


@pytest.mark.unit
class TestVerifyMcpToken:
    """Auth dependency tests for Bearer token validation."""

    def test_no_env_var_passes_through(self, monkeypatch: pytest.MonkeyPatch):
        """When MCP_AUTH_TOKEN is not set, auth is disabled (local dev mode)."""
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        # Should not raise
        result = verify_mcp_token(mock_request)
        assert result is None

    def test_valid_token_passes_through(self, monkeypatch: pytest.MonkeyPatch):
        """Valid Bearer token allows access."""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret123")

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer secret123"}

        # Should not raise
        result = verify_mcp_token(mock_request)
        assert result is None

    def test_invalid_token_raises_401(self, monkeypatch: pytest.MonkeyPatch):
        """Invalid Bearer token raises HTTPException 401."""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret123")

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer wrongtoken"}

        with pytest.raises(HTTPException) as exc_info:
            verify_mcp_token(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid token" in exc_info.value.detail

    def test_missing_authorization_header_raises_401(self, monkeypatch: pytest.MonkeyPatch):
        """Missing Authorization header raises HTTPException 401."""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret123")

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            verify_mcp_token(mock_request)

        assert exc_info.value.status_code == 401
        assert "Missing Bearer token" in exc_info.value.detail

    def test_malformed_header_no_bearer_prefix_raises_401(self, monkeypatch: pytest.MonkeyPatch):
        """Authorization header without 'Bearer ' prefix raises HTTPException 401."""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret123")

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "secret123"}

        with pytest.raises(HTTPException) as exc_info:
            verify_mcp_token(mock_request)

        assert exc_info.value.status_code == 401
        assert "Missing Bearer token" in exc_info.value.detail

    def test_empty_token_env_var_disables_auth(self, monkeypatch: pytest.MonkeyPatch):
        """Empty MCP_AUTH_TOKEN env var disables auth."""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "")

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        # Should not raise
        result = verify_mcp_token(mock_request)
        assert result is None

    def test_case_sensitive_bearer_prefix(self, monkeypatch: pytest.MonkeyPatch):
        """Authorization header is case-sensitive for 'Bearer ' prefix."""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret123")

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "bearer secret123"}

        with pytest.raises(HTTPException) as exc_info:
            verify_mcp_token(mock_request)

        assert exc_info.value.status_code == 401
        assert "Missing Bearer token" in exc_info.value.detail


# ===========================================================================
# SessionManager Tests
# ===========================================================================


@pytest.mark.unit
class TestSessionManager:
    """Session lifecycle management tests."""

    def test_create_returns_session_with_valid_uuid(self):
        """create() returns a session with a valid UUID session_id."""
        manager = SessionManager()
        app_state = MagicMock()

        session = manager.create(app_state)

        assert isinstance(session, SSESession)
        assert len(session.session_id) == 32  # UUID hex is 32 chars
        assert isinstance(session.server, LiveMCPServer)
        assert manager.active_count == 1

    def test_get_returns_session_and_updates_last_activity(self):
        """get() returns the session and updates last_activity timestamp."""
        manager = SessionManager()
        app_state = MagicMock()

        session = manager.create(app_state)
        original_activity = session.last_activity

        # Wait a bit and call get()
        time.sleep(0.01)
        retrieved = manager.get(session.session_id)

        assert retrieved is session
        assert retrieved.last_activity > original_activity

    def test_get_returns_none_for_unknown_id(self):
        """get() returns None for unknown session ID."""
        manager = SessionManager()

        result = manager.get("unknown-session-id")

        assert result is None

    def test_remove_removes_session(self):
        """remove() removes the session from the manager."""
        manager = SessionManager()
        app_state = MagicMock()

        session = manager.create(app_state)
        session_id = session.session_id

        assert manager.active_count == 1

        manager.remove(session_id)

        assert manager.active_count == 0
        assert manager.get(session_id) is None

    def test_remove_unknown_session_does_not_raise(self):
        """remove() on unknown session ID does not raise."""
        manager = SessionManager()

        # Should not raise
        manager.remove("unknown-id")

    def test_cleanup_stale_removes_expired_sessions(self, monkeypatch: pytest.MonkeyPatch):
        """_cleanup_stale() removes sessions older than SESSION_TTL_SECONDS."""
        from src.mcp import sse_transport as sse_module

        manager = SessionManager()
        app_state = MagicMock()

        # Create two sessions
        session1 = manager.create(app_state)
        session2 = manager.create(app_state)

        # Mock session1 as expired
        session1.last_activity = time.time() - 3700  # Older than 3600 seconds

        assert manager.active_count == 2

        # Trigger cleanup
        manager._cleanup_stale()

        # session1 should be removed, session2 should remain
        assert manager.active_count == 1
        assert manager.get(session1.session_id) is None
        assert manager.get(session2.session_id) is not None

    def test_max_capacity_eviction_removes_oldest_session(self, monkeypatch: pytest.MonkeyPatch):
        """When MAX_SESSIONS is reached, oldest session is evicted."""
        from src.mcp import sse_transport as sse_module

        # Temporarily set MAX_SESSIONS to 3 for testing
        original_max = sse_module.MAX_SESSIONS
        monkeypatch.setattr(sse_module, "MAX_SESSIONS", 3)

        manager = SessionManager()
        app_state = MagicMock()

        # Create 3 sessions (at capacity)
        session1 = manager.create(app_state)
        time.sleep(0.01)
        session2 = manager.create(app_state)
        time.sleep(0.01)
        session3 = manager.create(app_state)

        assert manager.active_count == 3

        # Create a 4th session - should evict session1 (oldest)
        session4 = manager.create(app_state)

        assert manager.active_count == 3
        assert manager.get(session1.session_id) is None
        assert manager.get(session2.session_id) is not None
        assert manager.get(session3.session_id) is not None
        assert manager.get(session4.session_id) is not None

        # Restore original
        monkeypatch.setattr(sse_module, "MAX_SESSIONS", original_max)


# ===========================================================================
# LiveMCPServer Tests
# ===========================================================================


@pytest.mark.unit
class TestLiveMCPServer:
    """LiveMCPServer tool execution tests."""

    @pytest.mark.asyncio
    async def test_rafi_get_calendar_calls_app_state_calendar_list_events(self):
        """rafi_get_calendar calls app_state.calendar.list_events()."""
        app_state = MagicMock()
        app_state.calendar = MagicMock()
        app_state.calendar.list_events = AsyncMock(return_value=[
            {"start": "2025-06-20 14:00", "summary": "Team Meeting"},
        ])

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_calendar", {"days": 7})

        assert "Team Meeting" in result
        app_state.calendar.list_events.assert_awaited_once_with(days_ahead=7)

    @pytest.mark.asyncio
    async def test_rafi_get_calendar_handles_no_events(self):
        """rafi_get_calendar returns 'No upcoming events' when calendar is empty."""
        app_state = MagicMock()
        app_state.calendar = MagicMock()
        app_state.calendar.list_events = AsyncMock(return_value=[])

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_calendar", {"days": 7})

        assert result == "No upcoming events."

    @pytest.mark.asyncio
    async def test_rafi_get_calendar_handles_missing_calendar_service(self):
        """rafi_get_calendar handles missing calendar service gracefully."""
        app_state = MagicMock(spec=[])  # No calendar attribute

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_calendar", {"days": 7})

        assert result == "Calendar service not available."

    @pytest.mark.asyncio
    async def test_rafi_get_calendar_handles_exception(self):
        """rafi_get_calendar returns error message when calendar.list_events raises."""
        app_state = MagicMock()
        app_state.calendar = MagicMock()
        app_state.calendar.list_events = AsyncMock(side_effect=RuntimeError("API error"))

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_calendar", {"days": 7})

        assert "Error fetching calendar" in result
        assert "API error" in result

    @pytest.mark.asyncio
    async def test_rafi_get_feedback_summary_queries_app_state_db(self):
        """rafi_get_feedback_summary queries app_state.db for feedback."""
        app_state = MagicMock()
        app_state.db = MagicMock()

        # Mock Supabase query chain
        mock_result = MagicMock()
        mock_result.data = [
            {"created_at": "2025-06-15T10:00:00", "rating": 8, "comment": "Great!"},
            {"created_at": "2025-06-14T09:00:00", "rating": 7, "comment": "Good"},
        ]

        table_mock = MagicMock()
        table_mock.select.return_value = table_mock
        table_mock.gte.return_value = table_mock
        table_mock.order.return_value = table_mock
        table_mock.limit.return_value = table_mock
        table_mock.execute.return_value = mock_result

        app_state.db.table.return_value = table_mock

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_feedback_summary", {"days": 7})

        assert "Feedback (2 entries" in result
        assert "rating=8" in result
        assert "Great!" in result
        app_state.db.table.assert_called_once_with("feedback")

    @pytest.mark.asyncio
    async def test_rafi_get_feedback_summary_handles_no_feedback(self):
        """rafi_get_feedback_summary handles empty feedback gracefully."""
        app_state = MagicMock()
        app_state.db = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []

        table_mock = MagicMock()
        table_mock.select.return_value = table_mock
        table_mock.gte.return_value = table_mock
        table_mock.order.return_value = table_mock
        table_mock.limit.return_value = table_mock
        table_mock.execute.return_value = mock_result

        app_state.db.table.return_value = table_mock

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_feedback_summary", {"days": 7})

        assert "No feedback in the last 7 days" in result

    @pytest.mark.asyncio
    async def test_rafi_get_feedback_summary_handles_missing_db(self):
        """rafi_get_feedback_summary handles missing db gracefully."""
        app_state = MagicMock(spec=[])  # No db attribute

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_feedback_summary", {"days": 7})

        assert result == "Database not available."

    @pytest.mark.asyncio
    async def test_rafi_get_feedback_summary_handles_exception(self):
        """rafi_get_feedback_summary returns error message on exception."""
        app_state = MagicMock()
        app_state.db = MagicMock()
        app_state.db.table.side_effect = RuntimeError("DB connection failed")

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_get_feedback_summary", {"days": 7})

        assert "Error fetching feedback" in result
        assert "DB connection failed" in result

    @pytest.mark.asyncio
    async def test_rafi_send_message_calls_channel_manager_send_to_preferred(self):
        """rafi_send_message calls app_state.channel_manager.send_to_preferred()."""
        app_state = MagicMock()
        app_state.channel_manager = MagicMock()
        app_state.channel_manager.send_to_preferred = AsyncMock()

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_send_message", {"message": "Hello world"})

        assert "Message sent successfully" in result
        assert "11 chars" in result
        app_state.channel_manager.send_to_preferred.assert_awaited_once_with("Hello world")

    @pytest.mark.asyncio
    async def test_rafi_send_message_handles_empty_message(self):
        """rafi_send_message handles empty message gracefully."""
        app_state = MagicMock()
        app_state.channel_manager = MagicMock()

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_send_message", {"message": ""})

        assert result == "No message provided."

    @pytest.mark.asyncio
    async def test_rafi_send_message_handles_missing_channel_manager(self):
        """rafi_send_message handles missing channel_manager gracefully."""
        app_state = MagicMock(spec=[])  # No channel_manager attribute

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_send_message", {"message": "Hello"})

        assert result == "Channel manager not available."

    @pytest.mark.asyncio
    async def test_rafi_send_message_handles_exception(self):
        """rafi_send_message returns error message on exception."""
        app_state = MagicMock()
        app_state.channel_manager = MagicMock()
        app_state.channel_manager.send_to_preferred = AsyncMock(side_effect=RuntimeError("Send failed"))

        server = LiveMCPServer(app_state)

        result = await server._execute_tool("rafi_send_message", {"message": "Hello"})

        assert "Error sending message" in result
        assert "Send failed" in result

    @pytest.mark.asyncio
    async def test_other_tools_fall_through_to_parent_mcp_server(self):
        """Non-live tools fall through to parent MCPServer._execute_tool()."""
        app_state = MagicMock()

        server = LiveMCPServer(app_state)

        # Mock parent's _execute_tool
        with patch("src.mcp.server.MCPServer._execute_tool", new_callable=AsyncMock) as mock_parent:
            mock_parent.return_value = "parent result"

            result = await server._execute_tool("rafi_get_user_context", {"key": "value"})

            assert result == "parent result"
            mock_parent.assert_awaited_once_with("rafi_get_user_context", {"key": "value"})


# ===========================================================================
# Route Tests
# ===========================================================================


@pytest.mark.unit
class TestRoutesMessagesEndpoint:
    """Route tests for POST /api/mcp/messages endpoint."""

    @pytest.mark.asyncio
    async def test_unknown_session_id_raises_404(self, monkeypatch: pytest.MonkeyPatch):
        """POST to /api/mcp/messages with unknown sessionId raises HTTPException 404."""
        from src.mcp import sse_transport as sse_module

        # Mock the global session manager to return None
        mock_manager = MagicMock()
        mock_manager.get.return_value = None
        monkeypatch.setattr(sse_module, "_session_manager", mock_manager)

        # Import the endpoint function
        from src.mcp.sse_transport import messages_endpoint

        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"jsonrpc": "2.0", "method": "initialize"})

        with pytest.raises(HTTPException) as exc_info:
            await messages_endpoint(mock_request, sessionId="unknown-session-id")

        assert exc_info.value.status_code == 404
        assert "Session not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_session_id_returns_accepted(self, monkeypatch: pytest.MonkeyPatch):
        """POST to /api/mcp/messages with valid sessionId returns accepted status."""
        from src.mcp import sse_transport as sse_module

        # Create a mock session
        mock_session = MagicMock(spec=SSESession)
        mock_session.server = MagicMock()
        mock_session.server.handle_message = AsyncMock(return_value={"result": "ok"})
        mock_session.queue = AsyncMock()
        mock_session.queue.put = AsyncMock()

        # Mock the global session manager
        mock_manager = MagicMock()
        mock_manager.get.return_value = mock_session
        monkeypatch.setattr(sse_module, "_session_manager", mock_manager)

        # Import the endpoint function
        from src.mcp.sse_transport import messages_endpoint

        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"jsonrpc": "2.0", "method": "ping"})

        result = await messages_endpoint(mock_request, sessionId="valid-session-id")

        assert result == {"status": "accepted"}
        mock_session.server.handle_message.assert_awaited_once()
        mock_session.queue.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_with_none_response_does_not_queue(self, monkeypatch: pytest.MonkeyPatch):
        """POST with message that returns None does not queue a response."""
        from src.mcp import sse_transport as sse_module

        # Create a mock session
        mock_session = MagicMock(spec=SSESession)
        mock_session.server = MagicMock()
        mock_session.server.handle_message = AsyncMock(return_value=None)
        mock_session.queue = AsyncMock()
        mock_session.queue.put = AsyncMock()

        # Mock the global session manager
        mock_manager = MagicMock()
        mock_manager.get.return_value = mock_session
        monkeypatch.setattr(sse_module, "_session_manager", mock_manager)

        # Import the endpoint function
        from src.mcp.sse_transport import messages_endpoint

        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"jsonrpc": "2.0", "method": "notification"})

        result = await messages_endpoint(mock_request, sessionId="valid-session-id")

        assert result == {"status": "accepted"}
        mock_session.server.handle_message.assert_awaited_once()
        mock_session.queue.put.assert_not_awaited()
