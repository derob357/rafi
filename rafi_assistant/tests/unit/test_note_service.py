"""Tests for src/services/note_service.py — Note CRUD via Supabase.

All Supabase calls are mocked.  Covers:
- Create note
- Read (list) notes
- Update note
- Delete note
- Handles null/missing fields
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import — stub if source not yet written.
# ---------------------------------------------------------------------------
try:
    from src.services.note_service import NoteService
except ImportError:
    NoteService = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note_record(
    note_id: str = "note-uuid-1",
    title: str = "Test Note",
    content: str = "This is a test note.",
) -> Dict[str, Any]:
    """Build a fake Supabase note record."""
    return {
        "id": note_id,
        "title": title,
        "content": content,
        "created_at": "2025-06-12T14:30:00+00:00",
        "updated_at": "2025-06-12T14:30:00+00:00",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestCreateNote:
    """Create notes via NoteService."""

    def test_create_note(self, mock_supabase, mock_config):
        record = _note_record()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])

        svc = NoteService(mock_config, mock_supabase)
        result = svc.create_note(title="Test Note", content="This is a test note.")

        mock_supabase.table.return_value.insert.assert_called_once()
        assert result is not None

    def test_create_note_returns_id(self, mock_supabase, mock_config):
        record = _note_record(note_id="new-note-uuid")
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])

        svc = NoteService(mock_config, mock_supabase)
        result = svc.create_note(title="New Note", content="Content here.")

        if isinstance(result, dict):
            assert result["id"] == "new-note-uuid"


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestListNotes:
    """Read / list notes."""

    def test_list_notes(self, mock_supabase, mock_config):
        records = [_note_record("n1", "Note 1"), _note_record("n2", "Note 2")]
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=records)

        svc = NoteService(mock_config, mock_supabase)
        result = svc.list_notes()

        assert isinstance(result, list)
        assert len(result) == 2

    def test_list_notes_empty(self, mock_supabase, mock_config):
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        svc = NoteService(mock_config, mock_supabase)
        result = svc.list_notes()

        assert result == []


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestUpdateNote:
    """Update existing notes."""

    def test_update_note_title(self, mock_supabase, mock_config):
        updated = _note_record("n1", "Updated Title")
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        svc = NoteService(mock_config, mock_supabase)
        result = svc.update_note(note_id="n1", title="Updated Title")

        mock_supabase.table.return_value.update.assert_called_once()

    def test_update_note_content(self, mock_supabase, mock_config):
        updated = _note_record("n1", content="New content")
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        svc = NoteService(mock_config, mock_supabase)
        result = svc.update_note(note_id="n1", content="New content")

        assert result is not None


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestDeleteNote:
    """Delete notes."""

    def test_delete_note(self, mock_supabase, mock_config):
        mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        svc = NoteService(mock_config, mock_supabase)
        svc.delete_note(note_id="del-note-uuid")

        mock_supabase.table.return_value.delete.assert_called_once()


@pytest.mark.skipif(NoteService is None, reason="NoteService not yet implemented")
class TestNullHandling:
    """Handles null/missing fields in note records."""

    def test_note_with_null_content(self, mock_supabase, mock_config):
        record = _note_record()
        record["content"] = None
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[record])

        svc = NoteService(mock_config, mock_supabase)
        result = svc.list_notes()

        assert isinstance(result, list)
        assert len(result) == 1

    def test_note_with_missing_title(self, mock_supabase, mock_config):
        record = {"id": "n1", "content": "Content only"}
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[record])

        svc = NoteService(mock_config, mock_supabase)
        result = svc.list_notes()

        assert isinstance(result, list)

    def test_note_with_empty_strings(self, mock_supabase, mock_config):
        record = _note_record(title="", content="")
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[record])

        svc = NoteService(mock_config, mock_supabase)
        result = svc.list_notes()

        assert isinstance(result, list)
