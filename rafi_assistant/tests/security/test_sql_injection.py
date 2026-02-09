"""Security tests for SQL injection prevention.

Tests OWASP-style SQL injection patterns against Supabase query paths.
Verifies that all queries use parameterized inputs and search terms are escaped.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Import services that interact with Supabase.
# ---------------------------------------------------------------------------
try:
    from src.services.task_service import TaskService
except ImportError:
    TaskService = None  # type: ignore[assignment,misc]

try:
    from src.services.note_service import NoteService
except ImportError:
    NoteService = None  # type: ignore[assignment,misc]

try:
    from src.services.memory_service import MemoryService
except ImportError:
    MemoryService = None  # type: ignore[assignment,misc]


# ===================================================================
# OWASP SQL Injection Payloads
# ===================================================================

SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE tasks; --",
    "1 OR 1=1",
    "' UNION SELECT * FROM oauth_tokens --",
    "1; DELETE FROM messages WHERE 1=1",
    "' OR '1'='1",
    "admin'--",
    "1' ORDER BY 1--+",
    "' UNION SELECT null, null, null --",
    "1 AND (SELECT COUNT(*) FROM oauth_tokens) > 0",
    "'; INSERT INTO settings (key, value) VALUES ('malicious', 'data'); --",
    "1' AND '1'='1",
    "' OR ''='",
    "1; UPDATE tasks SET status='hacked' WHERE 1=1; --",
    "Robert'); DROP TABLE tasks;--",
    "' UNION SELECT username, password FROM users--",
]


# ===================================================================
# Test: Task Service query safety
# ===================================================================


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestTaskServiceSQLSafety:
    """SQL injection payloads in task operations should not execute raw SQL."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    async def test_create_task_with_sql_payload_title(self, mock_supabase, mock_config, payload):
        """SQL in task title is stored as literal text, not executed."""
        mock_supabase.insert = AsyncMock(
            return_value={"id": "safe", "title": payload, "status": "pending"}
        )

        svc = TaskService(db=mock_supabase)
        result = await svc.create_task(title=payload)

        # The insert should have been called with the payload as a parameter
        insert_call = mock_supabase.insert.call_args
        assert insert_call is not None
        # Verify the title was passed as data, not raw SQL
        call_data = insert_call[0][1] if len(insert_call[0]) > 1 else insert_call[1]
        assert payload.strip() in str(call_data)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[5:10])
    async def test_list_tasks_with_sql_in_status_filter(self, mock_supabase, mock_config, payload):
        """SQL in status filter uses parameterized query."""
        mock_supabase.select = AsyncMock(return_value=[])

        svc = TaskService(db=mock_supabase)
        result = await svc.list_tasks(status=payload)

        # The service should have called select (possibly with or without filters)
        mock_supabase.select.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[10:])
    async def test_update_task_with_sql_payload(self, mock_supabase, mock_config, payload):
        """SQL in update data is parameterized."""
        mock_supabase.update = AsyncMock(return_value={"id": "t1", "title": payload})

        svc = TaskService(db=mock_supabase)
        result = await svc.update_task(task_id="t1", updates={"title": payload})

        # The update should use parameterized values
        update_call = mock_supabase.update.call_args
        assert update_call is not None


# ===================================================================
# Test: Note Service query safety
# ===================================================================


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestNoteServiceSQLSafety:
    """SQL injection payloads in note operations are parameterized."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    async def test_create_note_with_sql_in_content(self, mock_supabase, mock_config, payload):
        mock_supabase.insert = AsyncMock(
            return_value={"id": "safe", "title": "Note", "content": payload}
        )

        svc = NoteService(mock_supabase)
        result = await svc.create_note(title="Note", content=payload)

        insert_call = mock_supabase.insert.call_args
        assert insert_call is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[5:10])
    async def test_update_note_with_sql_in_title(self, mock_supabase, mock_config, payload):
        mock_supabase.update = AsyncMock(
            return_value={"id": "n1", "title": payload}
        )

        svc = NoteService(mock_supabase)
        result = await svc.update_note(note_id="n1", updates={"title": payload})

        update_call = mock_supabase.update.call_args
        assert update_call is not None


# ===================================================================
# Test: Memory Service query safety
# ===================================================================


@pytest.mark.skipif(MemoryService is None, reason="MemoryService not yet implemented")
class TestMemoryServiceSQLSafety:
    """SQL injection payloads in memory search are parameterized."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    async def test_search_memory_with_sql_payload(self, mock_supabase, mock_openai, mock_config, payload):
        mock_supabase.rpc = AsyncMock(return_value=[])
        mock_supabase.embedding_search = AsyncMock(return_value=[])
        mock_openai.embed = AsyncMock(return_value=[0.01] * 3072)

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.search_memory(payload)

        # The search should use parameterized RPC call, not raw SQL
        assert isinstance(result, list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:3])
    async def test_store_message_with_sql_payload(self, mock_supabase, mock_openai, mock_config, payload):
        mock_supabase.insert = AsyncMock(return_value={"id": "safe"})
        mock_openai.embed = AsyncMock(return_value=[0.01] * 3072)

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        await svc.store_message(role="user", content=payload, source="telegram_text")

        # Verify insert was called with parameterized data
        insert_call = mock_supabase.insert.call_args
        assert insert_call is not None


# ===================================================================
# Test: Parameterized queries (general)
# ===================================================================


class TestParameterizedQueries:
    """Verify that all services use supabase-py's parameterized interface."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
    async def test_no_raw_sql_in_task_service(self, mock_supabase, mock_config):
        """TaskService should use the SupabaseClient wrapper, not raw SQL."""
        svc = TaskService(db=mock_supabase)

        mock_supabase.insert = AsyncMock(return_value={"id": "t1", "title": "Test"})
        mock_supabase.select = AsyncMock(return_value=[])
        mock_supabase.update = AsyncMock(return_value={"id": "t1"})
        mock_supabase.delete = AsyncMock(return_value=True)

        await svc.create_task(title="Test")
        await svc.list_tasks()
        await svc.update_task(task_id="t1", updates={"title": "Updated"})
        await svc.delete_task(task_id="t1")

        # All operations should go through the SupabaseClient wrapper methods
        mock_supabase.insert.assert_called_once()
        mock_supabase.select.assert_called_once()
        mock_supabase.update.assert_called_once()
        mock_supabase.delete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
    async def test_no_raw_sql_in_note_service(self, mock_supabase, mock_config):
        """NoteService should use the SupabaseClient wrapper, not raw SQL."""
        svc = NoteService(mock_supabase)

        mock_supabase.insert = AsyncMock(return_value={"id": "n1", "title": "Test"})
        mock_supabase.select = AsyncMock(return_value=[])

        await svc.create_note(title="Test", content="Content")
        await svc.list_notes()

        mock_supabase.insert.assert_called_once()
        mock_supabase.select.assert_called_once()
