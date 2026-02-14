"""Semantic memory service for conversation history.

Stores messages with embeddings in Supabase/pgvector and provides
hybrid search (vector cosine similarity + full-text) for context recall.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.db.supabase_client import SupabaseClient
from src.llm.provider import LLMProvider
from src.utils.async_utils import await_if_needed

logger = logging.getLogger(__name__)

ALLOWED_SOURCES = {
    "telegram_text",
    "telegram_voice",
    "whatsapp_text",
    "twilio_call",
    "system",
}

SOURCE_ALIASES = {
    "desktop_text": "system",
    "desktop_voice": "system",
}


class MemoryService:
    """Conversation memory with semantic search capabilities."""

    def __init__(self, db: SupabaseClient, llm: LLMProvider) -> None:
        self._db = db
        self._llm = llm

    async def store_message(
        self,
        role: str,
        content: str,
        source: str = "telegram_text",
    ) -> Optional[dict[str, Any]]:
        """Store a message with its embedding in the messages table.

        Generates an embedding for the message content and stores both
        the text and vector in Supabase for later retrieval.

        Args:
            role: Message role ('user', 'assistant', 'system').
            content: Message text content.
            source: Message source ('telegram_text', 'telegram_voice', 'twilio_call', 'system').

        Returns:
            Stored message dict, or None on failure.
        """
        if not content or not content.strip():
            logger.debug("Skipping empty message storage")
            return None

        source = SOURCE_ALIASES.get(source, source)
        if source not in ALLOWED_SOURCES:
            logger.warning("Unknown message source '%s', normalizing to 'system'", source)
            source = "system"

        # Generate embedding
        embedding: Optional[list[float]] = None
        try:
            embedding = await self._llm.embed(content)
        except Exception as e:
            logger.warning(
                "Failed to generate embedding for message, storing without: %s", e
            )

        data: dict[str, Any] = {
            "role": role,
            "content": content,
            "source": source,
        }

        if embedding is not None:
            data["embedding"] = embedding

        result = await await_if_needed(self._db.insert("messages", data))

        # FALLBACK: If insert fails (likely due to missing 'desktop_voice' source in DB constraint),
        # try again with a guaranteed source.
        if not result and source != "system":
            logger.warning("Message storage failed with source '%s', trying fallback 'system'", source)
            data["source"] = "system"
            result = await await_if_needed(self._db.insert("messages", data))

        if result:
            logger.debug(
                "Stored %s message (source: %s, has_embedding: %s)",
                role,
                data["source"],
                embedding is not None,
            )
        else:
            logger.error("Failed to store message even with fallback")

        return result

    async def search_memory(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.35,
    ) -> list[dict[str, Any]]:
        """Search conversation history using hybrid search.

        Combines pgvector cosine similarity with PostgreSQL full-text search
        to find the most relevant past messages. Results below min_score
        are filtered out (OpenClaw-style threshold).

        Args:
            query: Natural language search query.
            limit: Maximum number of results (default 5).
            min_score: Minimum similarity score threshold (default 0.35).

        Returns:
            List of matching message dicts with similarity scores.
        """
        if not query or not query.strip():
            return []

        # Generate query embedding
        try:
            query_embedding = await self._llm.embed(query)
        except Exception as e:
            logger.warning("Failed to embed search query, falling back to text search: %s", e)
            return await self._text_search_fallback(query, limit)

        # Hybrid search via RPC — fetch extra candidates for score filtering
        candidate_count = limit * 4
        results = await await_if_needed(
            self._db.rpc(
                "hybrid_search_messages",
                {
                    "query_embedding": query_embedding,
                    "query_text": query,
                    "match_count": candidate_count,
                    "match_threshold": min_score,
                },
            )
        )

        if results and isinstance(results, list):
            # Filter by min_score and truncate to limit
            filtered = [
                r for r in results
                if r.get("similarity", 0) >= min_score
            ][:limit]
            logger.info(
                "Memory search: %d candidates -> %d results (min_score=%.2f) for: %s",
                len(results), len(filtered), min_score, query[:50],
            )
            return filtered

        # Fall back to vector-only search
        results = await await_if_needed(
            self._db.embedding_search(
                query_embedding=query_embedding,
                match_count=limit,
                match_threshold=min_score,
            )
        )

        if results:
            logger.info("Vector search returned %d results", len(results))
            return results

        # Final fallback to text search
        return await self._text_search_fallback(query, limit)

    async def _text_search_fallback(
        self,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fall back to simple text search when embedding search is unavailable.

        Args:
            query: Search query text.
            limit: Maximum results.

        Returns:
            List of matching message dicts.
        """
        try:
            response = (
                await self._db.client.table("messages")
                .select("id, role, content, source, created_at")
                .textSearch("content", query)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            results = response.data if response.data else []
            logger.info("Text search fallback returned %d results", len(results))
            return results
        except Exception as e:
            logger.error("Text search fallback failed: %s", e)
            return []

    async def get_recent_messages(
        self,
        limit: int = 20,
        *,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get the most recent messages for conversation context.

        Returns messages in chronological order (oldest first) suitable
        for building LLM context.

        Args:
            limit: Maximum number of messages to return (default 20).
            count: Optional alias for limit used by some callers.

        Returns:
            List of message dicts in chronological order.
        """
        effective_limit = count if count is not None else limit

        messages = await await_if_needed(
            self._db.select(
                "messages",
                columns="id, role, content, source, created_at",
                order_by="created_at",
                order_desc=True,
                limit=effective_limit,
            )
        )

        # Reverse to get chronological order (oldest first)
        messages.reverse()

        logger.debug("Retrieved %d recent messages for context", len(messages))
        return messages

    async def get_context_messages(
        self,
        query: Optional[str] = None,
        recent_limit: int = 20,
        memory_limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Build a conversation context combining recent messages and memory search.

        Gets the most recent messages for continuity, and if a query is provided,
        also searches memory for relevant historical messages that are not already
        in the recent set.

        Args:
            query: Optional search query to pull relevant historical messages.
            recent_limit: Number of recent messages to include.
            memory_limit: Number of memory search results to include.

        Returns:
            List of context message dicts in chronological order.
        """
        recent = await self.get_recent_messages(limit=recent_limit)
        recent_ids = {msg.get("id") for msg in recent}

        if query:
            memory_results = await self.search_memory(query, limit=memory_limit)
            # Add memory results that aren't already in recent messages
            extra_context = [
                msg for msg in memory_results
                if msg.get("id") not in recent_ids
            ]
            if extra_context:
                logger.debug(
                    "Adding %d memory results to context", len(extra_context)
                )
                # Prepend memory context before recent messages
                return extra_context + recent

        return recent
