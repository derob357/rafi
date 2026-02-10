"""LLM Manager for runtime provider switching.

Implements the LLMProvider interface while managing multiple backend
providers. Chat requests go to the active provider; embeddings always
go to OpenAI (the only provider with an embedding API).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Friendly aliases for provider names
_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "gpt": "openai",
    "openai": "openai",
    "anthropic": "anthropic",
    "groq": "groq",
    "gemini": "gemini",
    "google": "gemini",
    "llama": "groq",
}


class LLMManager(LLMProvider):
    """Manages multiple LLM providers with runtime switching.

    Implements the LLMProvider interface so it can be used as a drop-in
    replacement everywhere the codebase expects an LLMProvider.
    """

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        default: str,
        embedding_provider: Optional[LLMProvider] = None,
    ) -> None:
        if not providers:
            raise ValueError("At least one LLM provider must be configured")
        if default not in providers:
            raise ValueError(f"Default provider '{default}' not in available providers: {list(providers.keys())}")

        self._providers = providers
        self._active = default
        self._embedding_provider = embedding_provider or providers.get("openai") or next(iter(providers.values()))

        logger.info(
            "LLM Manager initialized. Active: %s, Available: %s",
            self._active,
            list(self._providers.keys()),
        )

    @property
    def active_name(self) -> str:
        """Return the name of the currently active provider."""
        return self._active

    @property
    def available(self) -> list[str]:
        """Return list of available provider names."""
        return list(self._providers.keys())

    def switch(self, name: str) -> str:
        """Switch the active provider.

        Args:
            name: Provider name or alias (e.g. 'groq', 'claude', 'gemini').

        Returns:
            The canonical name of the new active provider.

        Raises:
            ValueError: If the provider is not available.
        """
        canonical = _ALIASES.get(name.lower(), name.lower())
        if canonical not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ValueError(f"Provider '{name}' not available. Choose from: {available}")

        self._active = canonical
        logger.info("Switched LLM provider to: %s", canonical)
        return canonical

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Delegate chat to the active provider, falling back to others on failure."""
        # Build try order: active provider first, then the rest
        try_order = [self._active] + [n for n in self._providers if n != self._active]
        last_error: Optional[Exception] = None

        for name in try_order:
            provider = self._providers[name]
            try:
                result = await provider.chat(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if name != self._active:
                    logger.warning(
                        "Provider '%s' failed, fell back to '%s' successfully",
                        self._active,
                        name,
                    )
                return result
            except Exception as e:
                last_error = e
                logger.error(
                    "Provider '%s' failed: %s: %s",
                    name,
                    type(e).__name__,
                    str(e)[:200],
                )

        # All providers failed — return a graceful error response
        logger.critical("All LLM providers failed. Last error: %s", last_error)
        return {
            "role": "assistant",
            "content": "I'm having trouble reaching my AI services right now. Please try again in a moment.",
            "tool_calls": [],
            "finish_reason": "error",
        }

    async def embed(self, text: str) -> list[float]:
        """Delegate embedding to the embedding provider (always OpenAI).

        Returns an empty vector on failure so memory operations degrade
        gracefully instead of crashing.
        """
        try:
            return await self._embedding_provider.embed(text)
        except Exception as e:
            logger.error("Embedding failed: %s: %s", type(e).__name__, str(e)[:200])
            return []

    async def close(self) -> None:
        """Close all providers."""
        closed: set[int] = set()
        for name, provider in self._providers.items():
            pid = id(provider)
            if pid not in closed:
                try:
                    await provider.close()
                    closed.add(pid)
                except Exception as e:
                    logger.warning("Error closing provider '%s': %s", name, e)
