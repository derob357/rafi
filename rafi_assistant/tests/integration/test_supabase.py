"""Integration tests for Supabase client."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "Supabase integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("TEST_SUPABASE_URL"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestSupabaseIntegration:
    """Integration tests against live Supabase instance."""

    @pytest.fixture(autouse=True)
    def setup_client(self) -> None:
        from src.db.supabase_client import SupabaseClient

        from src.config.loader import SupabaseConfig

        config = SupabaseConfig(
            url=os.environ.get("TEST_SUPABASE_URL", "https://placeholder.supabase.co"),
            anon_key=os.environ.get("TEST_SUPABASE_ANON_KEY", "placeholder"),
            service_role_key=os.environ.get("TEST_SUPABASE_KEY", "placeholder"),
        )
        self.client = SupabaseClient(config=config)

    @pytest.mark.asyncio
    async def test_insert_and_select_task(self) -> None:
        # Insert
        result = await self.client.insert("tasks", {
            "title": "Integration test task",
            "description": "Created by test",
            "status": "pending",
        })
        assert result is not None
        task_id = result[0]["id"] if result else None
        assert task_id is not None

        # Select
        tasks = await self.client.select("tasks", filters={"id": task_id})
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Integration test task"

        # Cleanup
        await self.client.delete("tasks", record_id=task_id)

    @pytest.mark.asyncio
    async def test_update_task(self) -> None:
        result = await self.client.insert("tasks", {
            "title": "Update test",
            "status": "pending",
        })
        task_id = result[0]["id"] if result else None

        await self.client.update("tasks", record_id=task_id, data={
            "status": "completed",
        })

        updated = await self.client.select("tasks", filters={"id": task_id})
        assert updated[0]["status"] == "completed"

        await self.client.delete("tasks", record_id=task_id)

    @pytest.mark.asyncio
    async def test_embedding_search(self) -> None:
        """Test pgvector similarity search."""
        # This test requires messages with embeddings in the test database
        results = await self.client.embedding_search(
            table="messages",
            query_embedding=[0.1] * 3072,
            limit=5,
        )
        assert isinstance(results, list)
