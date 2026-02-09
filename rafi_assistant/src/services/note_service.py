"""Note management service using Supabase.

Provides CRUD operations for notes stored in the Supabase notes table.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.db.supabase_client import SupabaseClient
from src.utils.async_utils import await_if_needed

logger = logging.getLogger(__name__)


class NoteService:
    """Note CRUD operations backed by Supabase."""

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    async def create_note(
        self,
        title: str,
        content: str,
    ) -> Optional[dict[str, Any]]:
        """Create a new note.

        Args:
            title: Note title (required).
            content: Note body content.

        Returns:
            Created note dict, or None on failure.
        """
        if not title or not title.strip():
            logger.warning("Attempted to create note with empty title")
            return None

        data = {
            "title": title.strip(),
            "content": (content or "").strip(),
        }

        result = await await_if_needed(self._db.insert("notes", data))

        if result:
            logger.info("Created note: %s (ID: %s)", title, result.get("id", "N/A"))
        else:
            logger.error("Failed to create note: %s", title)

        return result

    async def list_notes(self) -> list[dict[str, Any]]:
        """List all notes ordered by most recently created.

        Returns:
            List of note dicts.
        """
        notes = await await_if_needed(
            self._db.select(
                "notes",
                order_by="created_at",
                order_desc=True,
            )
        )

        logger.info("Listed %d notes", len(notes))
        return notes

    async def get_note(self, note_id: str) -> Optional[dict[str, Any]]:
        """Get a specific note by its ID.

        Args:
            note_id: Note UUID.

        Returns:
            Note dict, or None if not found.
        """
        if not note_id:
            return None

        notes = await await_if_needed(
            self._db.select(
                "notes",
                filters={"id": note_id},
                limit=1,
            )
        )

        if notes:
            return notes[0]

        logger.debug("Note not found: %s", note_id)
        return None

    async def update_note(
        self,
        note_id: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update an existing note.

        Args:
            note_id: Note UUID to update.
            updates: Dictionary of fields to update. Supported keys: title, content.

        Returns:
            Updated note dict, or None on failure.
        """
        if not note_id:
            logger.warning("Attempted to update note with empty ID")
            return None

        allowed_fields = {"title", "content"}
        filtered_updates: dict[str, Any] = {
            k: v for k, v in updates.items() if k in allowed_fields and v is not None
        }

        if not filtered_updates:
            logger.warning("No valid update fields provided for note %s", note_id)
            return None

        result = await await_if_needed(
            self._db.update(
                "notes",
                filters={"id": note_id},
                data=filtered_updates,
            )
        )

        if result:
            logger.info("Updated note %s", note_id)
        else:
            logger.warning("Failed to update note %s", note_id)

        return result

    async def delete_note(self, note_id: str) -> bool:
        """Delete a note by its ID.

        Args:
            note_id: Note UUID to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        if not note_id:
            logger.warning("Attempted to delete note with empty ID")
            return False

        success = await await_if_needed(self._db.delete("notes", filters={"id": note_id}))

        if success:
            logger.info("Deleted note %s", note_id)
        else:
            logger.warning("Failed to delete note %s", note_id)

        return success

    async def search_notes(self, query: str) -> list[dict[str, Any]]:
        """Search notes by title or content using full-text search.

        Uses the Supabase RPC function or text search to find matching notes.

        Args:
            query: Search query string.

        Returns:
            List of matching note dicts.
        """
        if not query or not query.strip():
            return await self.list_notes()

        try:
            # Use Supabase text search on title and content
            result = await self._db.client.table("notes").select("*").or_(
                f"title.ilike.%{query}%,content.ilike.%{query}%"
            ).order("created_at", desc=True).execute()

            return result.data if result.data else []
        except Exception as e:
            logger.error("Failed to search notes: %s", e)
            return []
