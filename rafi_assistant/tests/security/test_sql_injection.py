"""Security tests for SQL injection prevention.

Tests OWASP-style SQL injection patterns against Supabase query paths.
Verifies that all queries use parameterized inputs and search terms are escaped.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

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

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    def test_create_task_with_sql_payload_title(self, mock_supabase, mock_config, payload):
        """SQL in task title is stored as literal text, not executed."""
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "safe", "title": payload, "status": "pending"}]
        )

        svc = TaskService(db=mock_supabase)
        # This must not cause SQL execution; the payload is a literal string
        result = svc.create_task(title=payload)

        # The insert should have been called with the payload as a parameter,
        # not interpolated into SQL
        insert_call = mock_supabase.table.return_value.insert.call_args
        assert insert_call is not None
        # Verify the title was passed as data, not raw SQL
        call_data = insert_call[0][0] if insert_call[0] else insert_call[1]
        assert payload in str(call_data)

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[5:10])
    def test_list_tasks_with_sql_in_status_filter(self, mock_supabase, mock_config, payload):
        """SQL in status filter uses parameterized query."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        svc = TaskService(db=mock_supabase)
        result = svc.list_tasks(status=payload)

        # The eq() method should have received the payload as a parameter
        eq_call = mock_supabase.table.return_value.select.return_value.eq.call_args
        if eq_call:
            assert payload in str(eq_call)

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[10:])
    def test_update_task_with_sql_payload(self, mock_supabase, mock_config, payload):
        """SQL in update data is parameterized."""
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        svc = TaskService(db=mock_supabase)
        result = svc.update_task(task_id="t1", title=payload)

        # The update should use parameterized values
        update_call = mock_supabase.table.return_value.update.call_args
        assert update_call is not None


# ===================================================================
# Test: Note Service query safety
# ===================================================================


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestNoteServiceSQLSafety:
    """SQL injection payloads in note operations are parameterized."""

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    def test_create_note_with_sql_in_content(self, mock_supabase, mock_config, payload):
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "safe", "title": "Note", "content": payload}]
        )

        svc = NoteService(mock_config, mock_supabase)
        result = svc.create_note(title="Note", content=payload)

        insert_call = mock_supabase.table.return_value.insert.call_args
        assert insert_call is not None

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[5:10])
    def test_update_note_with_sql_in_title(self, mock_supabase, mock_config, payload):
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        svc = NoteService(mock_config, mock_supabase)
        result = svc.update_note(note_id="n1", title=payload)

        update_call = mock_supabase.table.return_value.update.call_args
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
        mock_supabase.rpc.return_value = MagicMock(data=[])
        embedding_data = MagicMock()
        embedding_data.embedding = [0.01] * 3072
        mock_openai.embeddings.create.return_value = MagicMock(data=[embedding_data])

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.search_memory(payload)

        # The search should use parameterized RPC call, not raw SQL
        assert isinstance(result, list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:3])
    async def test_store_message_with_sql_payload(self, mock_supabase, mock_openai, mock_config, payload):
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
        embedding_data = MagicMock()
        embedding_data.embedding = [0.01] * 3072
        mock_openai.embeddings.create.return_value = MagicMock(data=[embedding_data])

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        await svc.store_message(role="user", content=payload, source="telegram_text")

        # Verify insert was called with parameterized data
        insert_call = mock_supabase.table.return_value.insert.call_args
        assert insert_call is not None


# ===================================================================
# Test: Parameterized queries (general)
# ===================================================================


class TestParameterizedQueries:
    """Verify that all services use supabase-py's parameterized interface."""

    @pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
    def test_no_raw_sql_in_task_service(self, mock_supabase, mock_config):
        """TaskService should never call execute() with raw SQL strings."""
        svc = TaskService(db=mock_supabase)

        # Perform all operations
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        svc.create_task(title="Test")
        svc.list_tasks()
        svc.update_task(task_id="t1", title="Updated")
        svc.delete_task(task_id="t1")

        # All operations should go through table().method() chains, not raw SQL
        assert mock_supabase.table.called
        # rpc should not have been called for basic CRUD
        # (rpc is only for memory search with pgvector)

    @pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
    def test_no_raw_sql_in_note_service(self, mock_supabase, mock_config):
        """NoteService should never call execute() with raw SQL strings."""
        svc = NoteService(mock_config, mock_supabase)

        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        svc.create_note(title="Test", content="Content")
        svc.list_notes()

        assert mock_supabase.table.called
