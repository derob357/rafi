"""Groq implementation of the LLM provider interface.

Uses the OpenAI-compatible API via the openai SDK with a custom base_url.
Groq does not support embeddings, so embed() delegates to OpenAI.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from src.config.loader import LLMConfig
from src.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqProvider(OpenAIProvider):
    """Groq-based LLM provider using their OpenAI-compatible API."""

    def __init__(self, config: LLMConfig, api_key: Optional[str] = None) -> None:
        key = api_key or config.groq_api_key or config.api_key
        model = GROQ_DEFAULT_MODEL
        super().__init__(config, api_key=key, base_url=GROQ_BASE_URL, model=model)

        # Separate OpenAI client for embeddings (Groq doesn't support them)
        openai_key = config.api_key
        self._openai_embed_client: Optional[AsyncOpenAI] = None
        if openai_key and not openai_key.startswith("PLACEHOLDER"):
            self._openai_embed_client = AsyncOpenAI(api_key=openai_key)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI (Groq has no embedding API)."""
        if self._openai_embed_client is None:
            raise RuntimeError(
                "Embedding requires an OpenAI API key. "
                "Set LLM_API_KEY to a valid OpenAI key for embeddings."
            )
        response = await self._openai_embed_client.embeddings.create(
            model=self._embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def close(self) -> None:
        """Close both the Groq and OpenAI clients."""
        await super().close()
        if self._openai_embed_client:
            await self._openai_embed_client.close()
