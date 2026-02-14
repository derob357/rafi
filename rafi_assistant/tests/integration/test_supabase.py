"""Integration tests for Supabase client."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env", override=False)

SKIP_REASON = "Supabase integration tests require live credentials"
HAS_CREDENTIALS = bool(
    os.environ.get("TEST_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
)


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestSupabaseIntegration:
    """Integration tests against live Supabase instance."""

    @pytest.fixture(autouse=True)
    async def setup_client(self) -> None:
        from src.db.supabase_client import SupabaseClient
        from src.config.loader import SupabaseConfig

        config = SupabaseConfig(
            url=os.environ.get("TEST_SUPABASE_URL") or os.environ.get("SUPABASE_URL", ""),
            anon_key=os.environ.get("TEST_SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY", ""),
            service_role_key=os.environ.get("TEST_SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        )
        self.client = SupabaseClient(config=config)
        await self.client.initialize()

    @pytest.mark.asyncio
    async def test_insert_and_select_task(self) -> None:
        # Insert
        result = await self.client.insert("tasks", {
            "title": "Integration test task",
            "description": "Created by test",
            "status": "pending",
        })
        assert result is not None
        task_id = result["id"]
        assert task_id is not None

        # Select
        tasks = await self.client.select("tasks", filters={"id": task_id})
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Integration test task"

        # Cleanup
        await self.client.delete("tasks", filters={"id": task_id})

    @pytest.mark.asyncio
    async def test_update_task(self) -> None:
        result = await self.client.insert("tasks", {
            "title": "Update test",
            "status": "pending",
        })
        assert result is not None
        task_id = result["id"]

        await self.client.update("tasks", filters={"id": task_id}, data={
            "status": "completed",
        })

        updated = await self.client.select("tasks", filters={"id": task_id})
        assert updated[0]["status"] == "completed"

        await self.client.delete("tasks", filters={"id": task_id})

    @pytest.mark.asyncio
    async def test_embedding_search(self) -> None:
        """Test pgvector similarity search."""
        results = await self.client.embedding_search(
            query_embedding=[0.1] * 1536,
            match_count=5,
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_feedback_table_accessible(self) -> None:
        """Test that the feedback table exists and is queryable."""
        results = await self.client.select("feedback", limit=1)
        assert isinstance(results, list)
