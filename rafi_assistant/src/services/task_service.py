"""Task management service using Supabase.

Provides CRUD operations for tasks stored in the Supabase tasks table,
including status tracking, due dates, and completion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.db.supabase_client import SupabaseClient
from src.utils.async_utils import await_if_needed

logger = logging.getLogger(__name__)


class TaskService:
    """Task CRUD operations backed by Supabase."""

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    async def create_task(
        self,
        title: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Create a new task.

        Args:
            title: Task title (required).
            description: Optional task description.
            due_date: Optional due date in ISO 8601 format.
            status: Optional initial status (defaults to 'pending').

        Returns:
            Created task dict, or None on failure.
        """
        if not title or not title.strip():
            logger.warning("Attempted to create task with empty title")
            return None

        valid_statuses = {"pending", "in_progress", "completed"}
        target_status = (status or "pending").strip()
        if target_status not in valid_statuses:
            logger.warning("Invalid status '%s' for new task, defaulting to pending", target_status)
            target_status = "pending"

        data: dict[str, Any] = {
            "title": title.strip(),
            "description": (description or "").strip(),
            "status": target_status,
        }

        if due_date:
            data["due_date"] = due_date

        result = await await_if_needed(self._db.insert("tasks", data))

        if result:
            logger.info("Created task: %s (ID: %s)", title, result.get("id", "N/A"))
        else:
            logger.error("Failed to create task: %s", title)

        return result

    async def list_tasks(
        self,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List tasks, optionally filtered by status.

        Args:
            status: Filter by status ('pending', 'in_progress', 'completed').
                If None, returns all tasks.

        Returns:
            List of task dicts ordered by created_at descending.
        """
        filters: Optional[dict[str, Any]] = None
        if status and status in ("pending", "in_progress", "completed"):
            filters = {"status": status}

        tasks = await await_if_needed(
            self._db.select(
                "tasks",
                filters=filters,
                order_by="created_at",
                order_desc=True,
            )
        )

        logger.info("Listed %d tasks (status filter: %s)", len(tasks), status or "all")
        return tasks

    async def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """Get a specific task by its ID.

        Args:
            task_id: Task UUID.

        Returns:
            Task dict, or None if not found.
        """
        if not task_id:
            return None

        tasks = await await_if_needed(
            self._db.select(
                "tasks",
                filters={"id": task_id},
                limit=1,
            )
        )

        if tasks:
            return tasks[0]

        logger.debug("Task not found: %s", task_id)
        return None

    async def update_task(
        self,
        task_id: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update an existing task.

        Args:
            task_id: Task UUID to update.
            updates: Dictionary of fields to update. Supported keys:
                title, description, status, due_date.

        Returns:
            Updated task dict, or None on failure.
        """
        if not task_id:
            logger.warning("Attempted to update task with empty ID")
            return None

        # Filter to only allowed update fields
        allowed_fields = {"title", "description", "status", "due_date"}
        filtered_updates: dict[str, Any] = {
            k: v for k, v in updates.items() if k in allowed_fields and v is not None
        }

        if not filtered_updates:
            logger.warning("No valid update fields provided for task %s", task_id)
            return None

        # Validate status if provided
        if "status" in filtered_updates:
            valid_statuses = {"pending", "in_progress", "completed"}
            if filtered_updates["status"] not in valid_statuses:
                logger.warning(
                    "Invalid status '%s' for task %s",
                    filtered_updates["status"],
                    task_id,
                )
                return None

        result = await await_if_needed(
            self._db.update(
                "tasks",
                filters={"id": task_id},
                data=filtered_updates,
            )
        )

        if result:
            logger.info("Updated task %s", task_id)
        else:
            logger.warning("Failed to update task %s", task_id)

        return result

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task by its ID.

        Args:
            task_id: Task UUID to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        if not task_id:
            logger.warning("Attempted to delete task with empty ID")
            return False

        success = await await_if_needed(self._db.delete("tasks", filters={"id": task_id}))

        if success:
            logger.info("Deleted task %s", task_id)
        else:
            logger.warning("Failed to delete task %s", task_id)

        return success

    async def complete_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """Mark a task as completed.

        Args:
            task_id: Task UUID to complete.

        Returns:
            Updated task dict, or None on failure.
        """
        return await self.update_task(task_id, {"status": "completed"})

    async def get_pending_tasks(self) -> list[dict[str, Any]]:
        """Get all pending (non-completed) tasks.

        Returns:
            List of pending and in_progress tasks.
        """
        pending = await self.list_tasks(status="pending")
        in_progress = await self.list_tasks(status="in_progress")
        return pending + in_progress

    async def get_overdue_tasks(self) -> list[dict[str, Any]]:
        """Get tasks that are past their due date and not completed.

        Returns:
            List of overdue task dicts.
        """
        now = datetime.now(timezone.utc).isoformat()
        all_tasks = await self.get_pending_tasks()

        overdue = []
        for task in all_tasks:
            due_date = task.get("due_date")
            if due_date and due_date < now:
                overdue.append(task)

        logger.debug("Found %d overdue tasks", len(overdue))
        return overdue
