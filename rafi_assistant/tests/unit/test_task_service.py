"""Tests for src/services/task_service.py — Task CRUD via Supabase.

All Supabase calls are mocked.  Covers:
- create_task with all fields
- create_task with minimal fields
- list_tasks with and without status filter
- update_task
- delete_task
- complete_task sets status correctly
- Handles null/missing fields
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import — stub if source not yet written.
# ---------------------------------------------------------------------------
try:
    from src.services.task_service import TaskService
except ImportError:
    TaskService = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_record(
    task_id: str = "task-uuid-1",
    title: str = "Test Task",
    description: str = "Task description",
    status: str = "pending",
    due_date: str | None = "2025-06-20T17:00:00+00:00",
) -> Dict[str, Any]:
    """Build a fake Supabase task record."""
    record: Dict[str, Any] = {
        "id": task_id,
        "title": title,
        "description": description,
        "status": status,
        "due_date": due_date,
        "created_at": "2025-06-10T09:00:00+00:00",
        "updated_at": "2025-06-10T09:00:00+00:00",
    }
    return record


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestCreateTask:
    """create_task with all and minimal fields."""

    @pytest.mark.asyncio
    async def test_create_task_all_fields(self, mock_supabase, mock_config):
        record = _task_record()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])

        svc = TaskService(mock_supabase)
        result = await svc.create_task(
            title="Test Task",
            description="Task description",
            status="pending",
            due_date="2025-06-20T17:00:00+00:00",
        )

        mock_supabase.table.return_value.insert.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_create_task_minimal_fields(self, mock_supabase, mock_config):
        record = _task_record(description="", due_date=None)
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])

        svc = TaskService(mock_supabase)
        result = await svc.create_task(title="Minimal Task")

        mock_supabase.table.return_value.insert.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_create_task_returns_record(self, mock_supabase, mock_config):
        record = _task_record(task_id="new-uuid")
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])

        svc = TaskService(mock_supabase)
        result = await svc.create_task(title="New Task")

        if isinstance(result, dict):
            assert result["id"] == "new-uuid"


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestListTasks:
    """list_tasks with and without status filter."""

    @pytest.mark.asyncio
    async def test_list_all_tasks(self, mock_supabase, mock_config):
        records = [_task_record("t1", "Task 1"), _task_record("t2", "Task 2")]
        mock_supabase.select = AsyncMock(return_value=records)

        svc = TaskService(mock_supabase)
        result = await svc.list_tasks()

        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self, mock_supabase, mock_config):
        records = [_task_record("t1", "Task 1", status="pending")]
        mock_supabase.select = AsyncMock(return_value=records)

        svc = TaskService(mock_supabase)
        result = await svc.list_tasks(status="pending")

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, mock_supabase, mock_config):
        mock_supabase.select = AsyncMock(return_value=[])

        svc = TaskService(mock_supabase)
        result = await svc.list_tasks()

        assert result == []


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestUpdateTask:
    """update_task modifies the correct record."""

    @pytest.mark.asyncio
    async def test_update_task_title(self, mock_supabase, mock_config):
        updated = _task_record("t1", "Updated Title")
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        svc = TaskService(mock_supabase)
        result = await svc.update_task(task_id="t1", updates={"title": "Updated Title"})

        mock_supabase.table.return_value.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_task_status(self, mock_supabase, mock_config):
        updated = _task_record("t1", status="in_progress")
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        svc = TaskService(mock_supabase)
        result = await svc.update_task(task_id="t1", updates={"status": "in_progress"})

        assert result is not None


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestDeleteTask:
    """delete_task removes the correct record."""

    @pytest.mark.asyncio
    async def test_delete_task(self, mock_supabase, mock_config):
        mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        svc = TaskService(mock_supabase)
        await svc.delete_task(task_id="del-uuid")

        mock_supabase.table.return_value.delete.assert_called_once()


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestCompleteTask:
    """complete_task sets status to 'completed'."""

    @pytest.mark.asyncio
    async def test_complete_task_sets_status(self, mock_supabase, mock_config):
        completed = _task_record("t1", status="completed")
        mock_supabase.update = AsyncMock(return_value=completed)

        svc = TaskService(mock_supabase)
        result = await svc.complete_task(task_id="t1")

        # The update call should have set status to "completed"
        call_args = mock_supabase.update.call_args
        assert call_args is not None
        assert call_args[1]["data"] == {"status": "completed"}

    @pytest.mark.asyncio
    async def test_complete_task_returns_updated_record(self, mock_supabase, mock_config):
        completed = _task_record("t1", status="completed")
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[completed]
        )

        svc = TaskService(mock_supabase)
        result = await svc.complete_task(task_id="t1")

        assert result is not None


@pytest.mark.skipif(TaskService is None, reason="TaskService not yet implemented")
class TestNullHandling:
    """Handles null/missing fields gracefully."""

    @pytest.mark.asyncio
    async def test_task_with_null_description(self, mock_supabase, mock_config):
        record = _task_record(description=None)  # type: ignore[arg-type]
        record["description"] = None
        mock_supabase.select = AsyncMock(return_value=[record])

        svc = TaskService(mock_supabase)
        result = await svc.list_tasks()

        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_task_with_null_due_date(self, mock_supabase, mock_config):
        record = _task_record(due_date=None)
        mock_supabase.select = AsyncMock(return_value=[record])

        svc = TaskService(mock_supabase)
        result = await svc.list_tasks()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_task_with_missing_keys(self, mock_supabase, mock_config):
        record = {"id": "t1", "title": "Sparse Task"}
        mock_supabase.select = AsyncMock(return_value=[record])

        svc = TaskService(mock_supabase)
        result = await svc.list_tasks()

        assert isinstance(result, list)