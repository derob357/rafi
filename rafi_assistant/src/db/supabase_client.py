"""Supabase client wrapper with connection management and query helpers.

Provides a centralized interface for all database operations including
generic CRUD, embedding search, and error handling.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import AsyncClient, acreate_client

from src.config.loader import SupabaseConfig

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Wrapper around the Supabase async client with helper methods."""

    def __init__(self, config: SupabaseConfig) -> None:
        self._config = config
        self._client: Optional[AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize the Supabase async client connection.

        Raises:
            ConnectionError: If the connection cannot be established.
        """
        try:
            self._client = await acreate_client(
                self._config.url,
                self._config.service_role_key,
            )
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.critical("Failed to initialize Supabase client: %s", e)
            raise ConnectionError(f"Supabase connection failed: {e}") from e

    @property
    def client(self) -> AsyncClient:
        """Get the underlying Supabase client, ensuring it is initialized."""
        if self._client is None:
            raise RuntimeError(
                "Supabase client not initialized. Call initialize() first."
            )
        return self._client

    async def insert(
        self,
        table: str,
        data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Insert a row into a table.

        Args:
            table: Table name.
            data: Dictionary of column names to values.

        Returns:
            The inserted row data, or None on failure.
        """
        try:
            response = await self.client.table(table).insert(data).execute()
            if response.data and len(response.data) > 0:
                logger.debug("Inserted row into '%s': %s", table, response.data[0].get("id", "N/A"))
                return response.data[0]
            logger.warning("Insert into '%s' returned no data", table)
            return None
        except Exception as e:
            logger.error("Failed to insert into '%s': %s", table, e)
            return None

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: Optional[dict[str, Any]] = None,
        order_by: Optional[str] = None,
        order_desc: bool = True,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Select rows from a table with optional filtering, ordering, and limits.

        Args:
            table: Table name.
            columns: Comma-separated column names or "*" for all.
            filters: Dictionary of column-name to exact-match value filters.
            order_by: Column name to order by.
            order_desc: Whether to order descending (default True).
            limit: Maximum number of rows to return.

        Returns:
            List of row dictionaries. Empty list on failure.
        """
        try:
            query = self.client.table(table).select(columns)

            if filters:
                for key, value in filters.items():
                    if key.endswith("__gte"):
                        query = query.gte(key[:-5], value)
                    elif key.endswith("__lte"):
                        query = query.lte(key[:-5], value)
                    elif key.endswith("__gt"):
                        query = query.gt(key[:-4], value)
                    elif key.endswith("__lt"):
                        query = query.lt(key[:-4], value)
                    elif key.endswith("__neq"):
                        query = query.neq(key[:-5], value)
                    else:
                        query = query.eq(key, value)

            if order_by:
                query = query.order(order_by, desc=order_desc)

            if limit is not None:
                query = query.limit(limit)

            response = await query.execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error("Failed to select from '%s': %s", table, e)
            return []

    async def update(
        self,
        table: str,
        filters: dict[str, Any],
        data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update rows matching filters in a table.

        Args:
            table: Table name.
            filters: Dictionary of column-name to exact-match value for WHERE clause.
            data: Dictionary of column names to new values.

        Returns:
            The first updated row, or None on failure.
        """
        try:
            query = self.client.table(table).update(data)
            for key, value in filters.items():
                query = query.eq(key, value)

            response = await query.execute()
            if response.data and len(response.data) > 0:
                logger.debug("Updated row(s) in '%s'", table)
                return response.data[0]
            logger.warning("Update in '%s' matched no rows", table)
            return None
        except Exception as e:
            logger.error("Failed to update '%s': %s", table, e)
            return None

    async def delete(
        self,
        table: str,
        filters: dict[str, Any],
    ) -> bool:
        """Delete rows matching filters from a table.

        Args:
            table: Table name.
            filters: Dictionary of column-name to exact-match value for WHERE clause.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        try:
            query = self.client.table(table).delete()
            for key, value in filters.items():
                query = query.eq(key, value)

            await query.execute()
            logger.debug("Deleted row(s) from '%s'", table)
            return True
        except Exception as e:
            logger.error("Failed to delete from '%s': %s", table, e)
            return False

    async def upsert(
        self,
        table: str,
        data: dict[str, Any],
        on_conflict: str = "id",
    ) -> Optional[dict[str, Any]]:
        """Insert or update a row based on conflict column.

        Args:
            table: Table name.
            data: Dictionary of column names to values.
            on_conflict: Column name(s) for conflict detection.

        Returns:
            The upserted row data, or None on failure.
        """
        try:
            response = (
                await self.client.table(table)
                .upsert(data, on_conflict=on_conflict)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error("Failed to upsert into '%s': %s", table, e)
            return None

    async def rpc(
        self,
        function_name: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Call a Supabase/PostgreSQL RPC function.

        Args:
            function_name: The name of the database function to call.
            params: Parameters to pass to the function.

        Returns:
            The function's return value, or None on failure.
        """
        try:
            response = await self.client.rpc(function_name, params or {}).execute()
            return response.data
        except Exception as e:
            logger.error("RPC call '%s' failed: %s", function_name, e)
            return None

    async def embedding_search(
        self,
        query_embedding: list[float],
        table: str = "messages",
        embedding_column: str = "embedding",
        match_count: int = 5,
        match_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Perform cosine similarity search using pgvector.

        Calls a Supabase RPC function 'match_messages' that performs
        cosine similarity search on the embedding column.

        Args:
            query_embedding: The query vector (list of floats).
            table: Table to search in (used for RPC function naming).
            embedding_column: Name of the vector column.
            match_count: Maximum number of matches to return.
            match_threshold: Minimum similarity threshold (0-1).

        Returns:
            List of matching rows with similarity scores.
        """
        result = await self.rpc(
            "match_messages",
            {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "match_threshold": match_threshold,
            },
        )

        if result is None:
            return []

        if isinstance(result, list):
            return result

        return []
