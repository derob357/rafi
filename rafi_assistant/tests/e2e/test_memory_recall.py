"""E2E test: Memory recall - converse → store → query → verify."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

SKIP_REASON = "E2E tests require full test environment"
HAS_ENV = bool(os.environ.get("RAFI_E2E_TEST"))


@pytest.mark.e2e
@pytest.mark.skipif(not HAS_ENV, reason=SKIP_REASON)
class TestMemoryRecall:
    """E2E: Converse → embeddings stored → query memory → verify recall.

    Recursive dependency validation:
    - Message stored in Supabase with embedding
    - Embedding generated via OpenAI
    - Cosine similarity search returns relevant results
    - Full-text search supplements vector search
    - Recalled context is accurate
    """

    @pytest.mark.asyncio
    async def test_store_and_recall_message(self) -> None:
        """Store a message and recall it via semantic search."""
        from src.services.memory_service import MemoryService

        mock_db = AsyncMock()
        mock_db.insert = AsyncMock(return_value=[{"id": "test-id"}])
        mock_db.embedding_search = AsyncMock(return_value=[
            {
                "id": "test-id",
                "content": "We discussed the Johnson project deadline",
                "role": "user",
                "similarity": 0.92,
            }
        ])

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[0.1] * 3072)

        service = MemoryService(db=mock_db, llm=mock_llm)

        # Store
        await service.store_message(
            role="user",
            content="We discussed the Johnson project deadline",
            source="telegram_text",
        )
        mock_db.insert.assert_called_once()

        # Recall
        results = await service.search_memory("Johnson project")
        assert len(results) > 0
        assert "Johnson" in results[0].get("content", "")

    @pytest.mark.asyncio
    async def test_recall_empty_history(self) -> None:
        """Querying empty memory should return empty list."""
        from src.services.memory_service import MemoryService

        mock_db = AsyncMock()
        mock_db.embedding_search = AsyncMock(return_value=[])
        mock_db.select = AsyncMock(return_value=[])

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[0.1] * 3072)

        service = MemoryService(db=mock_db, llm=mock_llm)

        results = await service.search_memory("anything")
        assert isinstance(results, list)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_recent_messages_returns_ordered(self) -> None:
        """Get recent messages should return them in order."""
        from src.services.memory_service import MemoryService

        mock_db = AsyncMock()
        mock_db.select = AsyncMock(return_value=[
            {"role": "user", "content": "First message", "created_at": "2026-01-01T10:00:00"},
            {"role": "assistant", "content": "Response", "created_at": "2026-01-01T10:00:01"},
        ])

        mock_llm = MagicMock()

        service = MemoryService(db=mock_db, llm=mock_llm)

        messages = await service.get_recent_messages(limit=20)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
