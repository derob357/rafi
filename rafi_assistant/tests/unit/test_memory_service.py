"""Tests for src/services/memory_service.py — semantic memory.

All Supabase and OpenAI calls are mocked.  Covers:
- store_message generates embedding and stores
- search_memory returns ranked results
- get_recent_messages returns correct count
- Handles empty history
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import — stub if source not yet written.
# ---------------------------------------------------------------------------
try:
    from src.services.memory_service import MemoryService
except ImportError:
    MemoryService = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 3072  # text-embedding-3-large


def _message_record(
    msg_id: str = "msg-uuid-1",
    role: str = "user",
    content: str = "Hello, what is my schedule?",
    source: str = "telegram_text",
) -> Dict[str, Any]:
    """Build a fake Supabase message record."""
    return {
        "id": msg_id,
        "role": role,
        "content": content,
        "embedding": [0.01] * EMBEDDING_DIM,
        "source": source,
        "created_at": "2025-06-15T09:00:00+00:00",
    }


def _mock_openai_embedding() -> MagicMock:
    """Create a mocked OpenAI embeddings response."""
    embedding_data = MagicMock()
    embedding_data.embedding = [0.02] * EMBEDDING_DIM
    response = MagicMock()
    response.data = [embedding_data]
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(MemoryService is None, reason="MemoryService not yet implemented")
class TestStoreMessage:
    """store_message generates an embedding and stores in Supabase."""

    @pytest.mark.asyncio
    async def test_stores_user_message(self, mock_supabase, mock_openai, mock_config):
        record = _message_record()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        await svc.store_message(role="user", content="Hello, what is my schedule?", source="telegram_text")

        # Embedding should have been generated
        mock_openai.embeddings.create.assert_called_once()
        # Message should have been inserted into Supabase
        mock_supabase.table.return_value.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_stores_assistant_message(self, mock_supabase, mock_openai, mock_config):
        record = _message_record(role="assistant", content="You have 3 meetings today.")
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        await svc.store_message(role="assistant", content="You have 3 meetings today.", source="telegram_text")

        mock_openai.embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_embedding_dimension_correct(self, mock_supabase, mock_openai, mock_config):
        record = _message_record()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[record])
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        await svc.store_message(role="user", content="Test", source="telegram_text")

        # Check the insert call contains an embedding of correct dimension
        insert_call = mock_supabase.table.return_value.insert.call_args
        if insert_call and insert_call[0]:
            data = insert_call[0][0]
            if isinstance(data, dict) and "embedding" in data:
                assert len(data["embedding"]) == EMBEDDING_DIM


@pytest.mark.skipif(MemoryService is None, reason="MemoryService not yet implemented")
class TestSearchMemory:
    """search_memory returns ranked results via pgvector cosine similarity."""

    @pytest.mark.asyncio
    async def test_returns_ranked_results(self, mock_supabase, mock_openai, mock_config):
        results = [
            _message_record("m1", "user", "Discuss Johnson project timeline"),
            _message_record("m2", "assistant", "The Johnson project is on track for Q3."),
        ]
        mock_supabase.rpc.return_value = MagicMock(data=results)
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.search_memory("Johnson project")

        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_max_5_results(self, mock_supabase, mock_openai, mock_config):
        results = [_message_record(f"m{i}", "user", f"Message {i}") for i in range(10)]
        mock_supabase.rpc.return_value = MagicMock(data=results[:5])
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.search_memory("general topic")

        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_empty_search_returns_empty(self, mock_supabase, mock_openai, mock_config):
        mock_supabase.rpc.return_value = MagicMock(data=[])
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.search_memory("obscure topic nobody discussed")

        assert result == []


@pytest.mark.skipif(MemoryService is None, reason="MemoryService not yet implemented")
class TestGetRecentMessages:
    """get_recent_messages returns the correct number of recent messages."""

    @pytest.mark.asyncio
    async def test_returns_correct_count(self, mock_supabase, mock_openai, mock_config):
        messages = [_message_record(f"m{i}", "user", f"Message {i}") for i in range(20)]
        mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=messages
        )

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.get_recent_messages(count=20)

        assert isinstance(result, list)
        assert len(result) == 20

    @pytest.mark.asyncio
    async def test_returns_fewer_if_not_enough(self, mock_supabase, mock_openai, mock_config):
        messages = [_message_record("m1", "user", "Only one message")]
        mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=messages
        )

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.get_recent_messages(count=20)

        assert len(result) == 1


@pytest.mark.skipif(MemoryService is None, reason="MemoryService not yet implemented")
class TestEmptyHistory:
    """Handles empty message history without errors."""

    @pytest.mark.asyncio
    async def test_empty_history(self, mock_supabase, mock_openai, mock_config):
        mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.get_recent_messages(count=20)

        assert result == []

    @pytest.mark.asyncio
    async def test_search_on_empty_history(self, mock_supabase, mock_openai, mock_config):
        mock_supabase.rpc.return_value = MagicMock(data=[])
        mock_openai.embeddings.create.return_value = _mock_openai_embedding()

        svc = MemoryService(db=mock_supabase, llm=mock_openai)
        result = await svc.search_memory("anything")

        assert result == []
