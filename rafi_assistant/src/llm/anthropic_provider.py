"""Anthropic/Claude implementation of the LLM provider interface.

Uses the anthropic async client for chat completions. Embeddings
fall back to OpenAI since Anthropic does not provide an embedding API.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import anthropic
from openai import AsyncOpenAI

from src.config.loader import LLMConfig
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 16.0


def _convert_openai_tools_to_anthropic(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert OpenAI-format tool definitions to Anthropic format.

    OpenAI uses: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Anthropic uses: {"name": ..., "description": ..., "input_schema": ...}
    """
    converted = []
    for tool in tools:
        func = tool.get("function", tool)
        converted.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {}),
        })
    return converted


def _convert_messages_for_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Separate system prompt and convert messages to Anthropic format.

    Returns:
        Tuple of (system_prompt, messages_without_system).
    """
    system_prompt = ""
    converted = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_prompt += content + "\n"
            continue

        if role == "tool":
            # Anthropic expects tool results as user messages with tool_result content
            converted.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content or "",
                    }
                ],
            })
            continue

        if role == "assistant" and msg.get("tool_calls"):
            # Convert assistant tool calls to Anthropic format
            content_blocks: list[dict[str, Any]] = []
            if content:
                content_blocks.append({"type": "text", "text": content})
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "input": args,
                })
            converted.append({"role": "assistant", "content": content_blocks})
            continue

        converted.append({"role": role, "content": content or ""})

    return system_prompt.strip(), converted


class AnthropicProvider(LLMProvider):
    """Anthropic Claude-based LLM provider with retry logic.

    Note: Anthropic does not provide an embedding API. This provider
    uses OpenAI for embeddings when an OpenAI API key is available
    via the OPENAI_API_KEY environment variable or the llm config.
    """

    def __init__(self, config: LLMConfig, openai_api_key: Optional[str] = None) -> None:
        self._config = config
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self._model = config.model
        self._default_temperature = config.temperature
        self._default_max_tokens = config.max_tokens
        self._embedding_model = config.embedding_model

        # Embedding client (Anthropic doesn't have embeddings, so use OpenAI)
        import os
        oai_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self._openai_client: Optional[AsyncOpenAI] = None
        if oai_key:
            self._openai_client = AsyncOpenAI(api_key=oai_key)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to Anthropic Claude."""
        temp = temperature if temperature is not None else self._default_temperature
        tokens = max_tokens if max_tokens is not None else self._default_max_tokens

        system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": anthropic_messages,
            "max_tokens": tokens,
            "temperature": temp,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if tools:
            kwargs["tools"] = _convert_openai_tools_to_anthropic(tools)

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.messages.create(**kwargs)

                # Extract content and tool calls from Anthropic response
                text_content = ""
                tool_calls: list[dict[str, Any]] = []

                for block in response.content:
                    if block.type == "text":
                        text_content += block.text
                    elif block.type == "tool_use":
                        tool_calls.append({
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.input),
                            },
                        })

                result: dict[str, Any] = {
                    "role": "assistant",
                    "content": text_content or None,
                    "tool_calls": tool_calls,
                    "finish_reason": response.stop_reason,
                }

                logger.debug(
                    "Anthropic chat completed. Model: %s, Stop reason: %s, "
                    "Input tokens: %s, Output tokens: %s",
                    self._model,
                    response.stop_reason,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )

                return result

            except anthropic.RateLimitError as e:
                last_error = e
                delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                logger.warning(
                    "Anthropic rate limit hit (attempt %d/%d). Retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

            except anthropic.APIError as e:
                if hasattr(e, "status_code") and e.status_code and e.status_code >= 500:
                    last_error = e
                    delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                    logger.warning(
                        "Anthropic server error %s (attempt %d/%d). Retrying in %.1fs",
                        e.status_code,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        logger.error("Anthropic chat failed after %d attempts", MAX_RETRIES)
        raise last_error or RuntimeError("Anthropic chat failed with no specific error")

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding using OpenAI (Anthropic lacks embedding API).

        Falls back to OpenAI's embedding API since Anthropic does not
        provide one. Requires an OpenAI API key to be configured.
        """
        if self._openai_client is None:
            raise RuntimeError(
                "Embedding requires OpenAI API key. Set OPENAI_API_KEY environment "
                "variable or provide openai_api_key to AnthropicProvider."
            )

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._openai_client.embeddings.create(
                    model=self._embedding_model,
                    input=text,
                )
                return response.data[0].embedding
            except Exception as e:
                last_error = e
                delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                logger.warning(
                    "Embedding error (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error("Embedding failed after %d attempts", MAX_RETRIES)
        raise last_error or RuntimeError("Embedding failed with no specific error")

    async def close(self) -> None:
        """Close the underlying HTTP clients."""
        try:
            await self._client.close()
            if self._openai_client:
                await self._openai_client.close()
            logger.debug("Anthropic client closed")
        except Exception as e:
            logger.warning("Error closing Anthropic client: %s", e)
