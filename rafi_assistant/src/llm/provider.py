"""Abstract base class for LLM providers.

Defines the interface that all LLM implementations (OpenAI, Anthropic, etc.)
must conform to, enabling provider-agnostic code throughout the application.
"""

from __future__ import annotations

import abc
from typing import Any, Optional


class LLMProvider(abc.ABC):
    """Abstract interface for language model providers.

    All LLM implementations must provide async methods for chat completion
    (with optional tool/function calling) and text embedding.
    """

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to the LLM.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                Roles are typically 'system', 'user', 'assistant', 'tool'.
            tools: Optional list of tool/function definition dicts for
                function calling. Format follows the OpenAI tool schema.
            temperature: Optional temperature override (0.0-2.0).
            max_tokens: Optional max tokens override for the response.

        Returns:
            A dictionary containing at minimum:
                - "content": The text response (str or None if tool call).
                - "tool_calls": List of tool call dicts (if any), each with:
                    - "id": Tool call ID.
                    - "function": {"name": str, "arguments": str (JSON)}.
                - "role": "assistant"
                - "finish_reason": Why the model stopped generating.

        Raises:
            Exception: On API errors after retries are exhausted.
        """
        ...

    @abc.abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
            For OpenAI text-embedding-3-large, this is 3072 dimensions.

        Raises:
            Exception: On API errors after retries are exhausted.
        """
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        ...
