"""OpenAI implementation of the LLM provider interface.

Uses the openai async client for chat completions and embeddings,
with exponential backoff on rate limits and transient errors.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError

from src.config.loader import LLMConfig
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 16.0


class OpenAIProvider(LLMProvider):
    """OpenAI-based LLM provider with retry logic."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(api_key=config.api_key)
        self._model = config.model
        self._embedding_model = config.embedding_model
        self._default_temperature = config.temperature
        self._default_max_tokens = config.max_tokens

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to OpenAI.

        Implements exponential backoff on RateLimitError and transient API errors.
        If context is too long, attempts to truncate conversation history and retry.
        """
        temp = temperature if temperature is not None else self._default_temperature
        tokens = max_tokens if max_tokens is not None else self._default_max_tokens

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                message = choice.message

                result: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [],
                    "finish_reason": choice.finish_reason,
                }

                if message.tool_calls:
                    result["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]

                logger.debug(
                    "OpenAI chat completed. Model: %s, Finish reason: %s, "
                    "Prompt tokens: %s, Completion tokens: %s",
                    self._model,
                    choice.finish_reason,
                    response.usage.prompt_tokens if response.usage else "N/A",
                    response.usage.completion_tokens if response.usage else "N/A",
                )

                return result

            except RateLimitError as e:
                last_error = e
                delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                logger.warning(
                    "OpenAI rate limit hit (attempt %d/%d). Retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

            except APIError as e:
                # Handle context length exceeded by truncating history
                if "context_length_exceeded" in str(e).lower() or (
                    hasattr(e, "code") and e.code == "context_length_exceeded"
                ):
                    logger.warning("Context length exceeded. Truncating conversation history.")
                    # Keep system message and last few messages
                    system_msgs = [m for m in messages if m.get("role") == "system"]
                    other_msgs = [m for m in messages if m.get("role") != "system"]
                    # Keep last half of non-system messages
                    half = max(1, len(other_msgs) // 2)
                    messages = system_msgs + other_msgs[-half:]
                    kwargs["messages"] = messages
                    last_error = e
                    continue

                # Transient server errors
                if hasattr(e, "status_code") and e.status_code and e.status_code >= 500:
                    last_error = e
                    delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                    logger.warning(
                        "OpenAI server error %s (attempt %d/%d). Retrying in %.1fs",
                        e.status_code,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

            except APITimeoutError as e:
                last_error = e
                delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                logger.warning(
                    "OpenAI timeout (attempt %d/%d). Retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error("OpenAI chat failed after %d attempts", MAX_RETRIES)
        raise last_error or RuntimeError("OpenAI chat failed with no specific error")

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding using OpenAI's embedding API.

        Uses text-embedding-3-large by default (3072 dimensions).
        """
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self._embedding_model,
                    input=text,
                )
                embedding = response.data[0].embedding
                logger.debug(
                    "Generated embedding with %d dimensions",
                    len(embedding),
                )
                return embedding

            except RateLimitError as e:
                last_error = e
                delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                logger.warning(
                    "OpenAI embedding rate limit (attempt %d/%d). Retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

            except (APIError, APITimeoutError) as e:
                last_error = e
                delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                logger.warning(
                    "OpenAI embedding error (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error("OpenAI embedding failed after %d attempts", MAX_RETRIES)
        raise last_error or RuntimeError("OpenAI embedding failed with no specific error")

    async def close(self) -> None:
        """Close the underlying OpenAI async client."""
        try:
            await self._client.close()
            logger.debug("OpenAI client closed")
        except Exception as e:
            logger.warning("Error closing OpenAI client: %s", e)
