"""LLM Manager for runtime provider switching with cost-based routing.

Implements the LLMProvider interface while managing multiple backend
providers. Chat requests go to the active provider; embeddings always
go to OpenAI (the only provider with an embedding API).

Cost-based routing sends simple queries to cheaper/faster models
(Groq, Gemini) and complex queries to more capable models (OpenAI, Anthropic).
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

# Cost tiers: lower number = cheaper. Used for routing simple queries.
_COST_TIER: dict[str, int] = {
    "groq": 1,
    "gemini": 2,
    "openai": 3,
    "anthropic": 4,
}

# Keywords suggesting a complex query that needs a capable model
_COMPLEX_INDICATORS = [
    "analyze", "compare", "evaluate", "research", "explain in detail",
    "write a report", "create a plan", "review", "audit", "summarize",
    "multiple", "all of", "comprehensive", "thorough",
]

# Keywords suggesting a simple query that can use a cheaper model
_SIMPLE_INDICATORS = [
    "what time", "weather", "reminder", "set", "quick",
    "yes", "no", "ok", "sure", "thanks",
]


class LLMManager(LLMProvider):
    """Manages multiple LLM providers with runtime switching and cost-based routing.

    Implements the LLMProvider interface so it can be used as a drop-in
    replacement everywhere the codebase expects an LLMProvider.
    """

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        default: str,
        embedding_provider: Optional[LLMProvider] = None,
        cost_routing_enabled: bool = False,
    ) -> None:
        if not providers:
            raise ValueError("At least one LLM provider must be configured")
        if default not in providers:
            raise ValueError(f"Default provider '{default}' not in available providers: {list(providers.keys())}")

        self._providers = providers
        self._active = default
        self._embedding_provider = embedding_provider or providers.get("openai") or next(iter(providers.values()))
        self._cost_routing = cost_routing_enabled

        logger.info(
            "LLM Manager initialized. Active: %s, Available: %s, Cost routing: %s",
            self._active,
            list(self._providers.keys()),
            self._cost_routing,
        )

    @property
    def active_name(self) -> str:
        """Return the name of the currently active provider."""
        return self._active

    @property
    def available(self) -> list[str]:
        """Return list of available provider names."""
        return list(self._providers.keys())

    @property
    def cost_routing_enabled(self) -> bool:
        """Whether cost-based routing is active."""
        return self._cost_routing

    @cost_routing_enabled.setter
    def cost_routing_enabled(self, value: bool) -> None:
        self._cost_routing = value
        logger.info("Cost routing %s", "enabled" if value else "disabled")

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

    def _select_provider_for_query(self, messages: list[dict[str, Any]]) -> str:
        """Select the best provider based on query complexity.

        Simple queries → cheapest available provider
        Complex queries → active (configured) provider

        Args:
            messages: The message list being sent to the LLM.

        Returns:
            Provider name to use.
        """
        if not self._cost_routing:
            return self._active

        # Only route based on the last user message
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = msg.get("content", "").lower()
                break

        if not user_text:
            return self._active

        # Check for complexity indicators
        is_complex = any(indicator in user_text for indicator in _COMPLEX_INDICATORS)
        is_simple = any(indicator in user_text for indicator in _SIMPLE_INDICATORS)

        # Short messages are likely simple
        if len(user_text) < 30 and not is_complex:
            is_simple = True

        if is_simple and not is_complex:
            # Route to cheapest available provider
            sorted_providers = sorted(
                self._providers.keys(),
                key=lambda n: _COST_TIER.get(n, 99),
            )
            selected = sorted_providers[0]
            if selected != self._active:
                logger.debug(
                    "Cost routing: simple query → %s (instead of %s)",
                    selected,
                    self._active,
                )
            return selected

        return self._active

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Delegate chat to the selected provider, falling back to others on failure."""
        # Select provider (cost routing or default)
        selected = self._select_provider_for_query(messages)

        # Build try order: selected provider first, then the rest
        try_order = [selected] + [n for n in self._providers if n != selected]
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
                if name != selected:
                    logger.warning(
                        "Provider '%s' failed, fell back to '%s' successfully",
                        selected,
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
