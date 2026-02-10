"""Google Gemini implementation of the LLM provider interface.

Uses Google's OpenAI-compatible API via the openai SDK with a custom base_url.
Gemini does not support OpenAI-format embeddings, so embed() delegates to OpenAI.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from src.config.loader import LLMConfig
from src.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider(OpenAIProvider):
    """Google Gemini-based LLM provider using their OpenAI-compatible API."""

    def __init__(self, config: LLMConfig, api_key: Optional[str] = None) -> None:
        key = api_key or config.gemini_api_key or config.api_key
        model = GEMINI_DEFAULT_MODEL
        super().__init__(config, api_key=key, base_url=GEMINI_BASE_URL, model=model)

        # Separate OpenAI client for embeddings (Gemini compat endpoint doesn't support them)
        openai_key = config.api_key
        self._openai_embed_client: Optional[AsyncOpenAI] = None
        if openai_key and not openai_key.startswith("PLACEHOLDER"):
            self._openai_embed_client = AsyncOpenAI(api_key=openai_key)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI (Gemini compat API lacks embeddings)."""
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
        """Close both the Gemini and OpenAI clients."""
        await super().close()
        if self._openai_embed_client:
            await self._openai_embed_client.close()
