"""Tests for LLM providers and the LLM Manager.

Covers:
- OpenAIProvider: chat, embed, base_url/api_key overrides
- AnthropicProvider: chat, message conversion, default model selection
- GroqProvider: correct base_url, model, embedding fallback
- GeminiProvider: correct base_url, model, embedding fallback
- LLMManager: switching, failover, graceful degradation, embed fallback
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.loader import LLMConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def llm_config() -> LLMConfig:
    """Minimal valid LLMConfig for testing."""
    return LLMConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test-key",
        embedding_model="text-embedding-3-small",
        max_tokens=4096,
        temperature=0.7,
        groq_api_key="gsk-test-groq",
        gemini_api_key="ai-test-gemini",
        anthropic_api_key="sk-ant-test-anthropic",
    )


@pytest.fixture
def mock_chat_response() -> MagicMock:
    """Standard mock for OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = "Hello from mock"
    choice.message.tool_calls = None
    choice.finish_reason = "stop"

    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    return response


@pytest.fixture
def mock_embed_response() -> MagicMock:
    """Standard mock for OpenAI embedding response."""
    data = MagicMock()
    data.embedding = [0.1] * 1536

    response = MagicMock()
    response.data = [data]
    return response


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    """Tests for the OpenAI provider."""

    @pytest.mark.asyncio
    async def test_chat_returns_expected_format(self, llm_config, mock_chat_response):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_chat_response)

            from src.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider(config=llm_config)
            provider._client = instance

            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

            assert result["role"] == "assistant"
            assert result["content"] == "Hello from mock"
            assert result["tool_calls"] == []
            assert result["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_embed_returns_vector(self, llm_config, mock_embed_response):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.embeddings.create = AsyncMock(return_value=mock_embed_response)

            from src.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider(config=llm_config)
            provider._client = instance

            result = await provider.embed("test text")

            assert len(result) == 1536
            assert result[0] == 0.1

    def test_custom_base_url_passed_to_client(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            from src.llm.openai_provider import OpenAIProvider
            OpenAIProvider(config=llm_config, base_url="https://custom.api/v1")

            MockClient.assert_called_with(api_key="sk-test-key", base_url="https://custom.api/v1")

    def test_custom_api_key_overrides_config(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            from src.llm.openai_provider import OpenAIProvider
            OpenAIProvider(config=llm_config, api_key="sk-override")

            MockClient.assert_called_with(api_key="sk-override")

    def test_custom_model_overrides_config(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            from src.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider(config=llm_config, model="gpt-4o-mini")

            assert provider._model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls(self, llm_config):
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_weather"
        tool_call.function.arguments = '{"location": "NYC"}'

        choice = MagicMock()
        choice.message.content = None
        choice.message.tool_calls = [tool_call]
        choice.finish_reason = "tool_calls"

        response = MagicMock()
        response.choices = [choice]
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 5

        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(return_value=response)

            from src.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider(config=llm_config)
            provider._client = instance

            result = await provider.chat(
                messages=[{"role": "user", "content": "weather?"}],
                tools=[{"type": "function", "function": {"name": "get_weather"}}],
            )

            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["function"]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    """Tests for the Anthropic provider."""

    def test_default_model_when_provider_is_openai(self, llm_config):
        """When config.provider is 'openai', Anthropic should use its own default model."""
        with patch("src.llm.anthropic_provider.anthropic") as mock_anthropic:
            from src.llm.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider(config=llm_config, api_key="sk-ant-test")

            assert provider._model == AnthropicProvider.ANTHROPIC_DEFAULT_MODEL

    def test_uses_config_model_when_provider_is_anthropic(self):
        config = LLMConfig(
            provider="anthropic",
            model="claude-opus-4-6",
            api_key="sk-ant-test",
        )
        with patch("src.llm.anthropic_provider.anthropic"):
            from src.llm.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider(config=config)

            assert provider._model == "claude-opus-4-6"

    def test_explicit_model_overrides_all(self, llm_config):
        with patch("src.llm.anthropic_provider.anthropic"):
            from src.llm.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider(config=llm_config, model="claude-haiku-4-5-20251001")

            assert provider._model == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_chat_returns_expected_format(self, llm_config):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello from Claude"

        response = MagicMock()
        response.content = [text_block]
        response.stop_reason = "end_turn"
        response.usage.input_tokens = 10
        response.usage.output_tokens = 5

        with patch("src.llm.anthropic_provider.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            from src.llm.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider(config=llm_config, api_key="sk-ant-test")
            provider._client = mock_client

            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

            assert result["role"] == "assistant"
            assert result["content"] == "Hello from Claude"
            assert result["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_chat_with_tool_use(self, llm_config):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_123"
        tool_block.name = "get_weather"
        tool_block.input = {"location": "NYC"}

        response = MagicMock()
        response.content = [tool_block]
        response.stop_reason = "tool_use"
        response.usage.input_tokens = 10
        response.usage.output_tokens = 5

        with patch("src.llm.anthropic_provider.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            from src.llm.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider(config=llm_config, api_key="sk-ant-test")
            provider._client = mock_client

            result = await provider.chat(
                messages=[{"role": "user", "content": "weather?"}],
                tools=[{"type": "function", "function": {"name": "get_weather", "description": "Get weather", "parameters": {}}}],
            )

            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["function"]["name"] == "get_weather"
            assert json.loads(result["tool_calls"][0]["function"]["arguments"]) == {"location": "NYC"}


class TestAnthropicMessageConversion:
    """Tests for Anthropic message format conversion helpers."""

    def test_system_prompt_extracted(self):
        from src.llm.anthropic_provider import _convert_messages_for_anthropic

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, converted = _convert_messages_for_anthropic(messages)

        assert system == "You are helpful."
        assert len(converted) == 1
        assert converted[0]["role"] == "user"

    def test_tool_result_converted_to_user_message(self):
        from src.llm.anthropic_provider import _convert_messages_for_anthropic

        messages = [
            {"role": "tool", "tool_call_id": "call_1", "content": "72F sunny"},
        ]
        _, converted = _convert_messages_for_anthropic(messages)

        assert converted[0]["role"] == "user"
        assert converted[0]["content"][0]["type"] == "tool_result"
        assert converted[0]["content"][0]["tool_use_id"] == "call_1"

    def test_tool_definitions_converted(self):
        from src.llm.anthropic_provider import _convert_openai_tools_to_anthropic

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = _convert_openai_tools_to_anthropic(openai_tools)

        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather"
        assert "input_schema" in result[0]


# ---------------------------------------------------------------------------
# GroqProvider
# ---------------------------------------------------------------------------


class TestGroqProvider:
    """Tests for the Groq provider."""

    def test_uses_groq_base_url(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            from src.llm.groq_provider import GroqProvider, GROQ_BASE_URL
            GroqProvider(config=llm_config)

            # First call is the base class (Groq client), check it uses the right URL
            call_args = MockClient.call_args_list[0]
            assert call_args.kwargs.get("base_url") == GROQ_BASE_URL

    def test_uses_groq_api_key(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            from src.llm.groq_provider import GroqProvider
            GroqProvider(config=llm_config)

            call_args = MockClient.call_args_list[0]
            assert call_args.kwargs.get("api_key") == "gsk-test-groq"

    def test_uses_default_groq_model(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            from src.llm.groq_provider import GroqProvider, GROQ_DEFAULT_MODEL
            provider = GroqProvider(config=llm_config)

            assert provider._model == GROQ_DEFAULT_MODEL

    @pytest.mark.asyncio
    async def test_embed_uses_openai_fallback(self, llm_config, mock_embed_response):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            from src.llm.groq_provider import GroqProvider
            provider = GroqProvider(config=llm_config)

            mock_oai = AsyncMock()
            mock_oai.embeddings.create = AsyncMock(return_value=mock_embed_response)
            provider._openai_embed_client = mock_oai

            result = await provider.embed("test")

            assert len(result) == 1536
            mock_oai.embeddings.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_embed_raises_without_openai_key(self):
        config = LLMConfig(
            provider="openai",
            model="gpt-4o",
            api_key="PLACEHOLDER",
            groq_api_key="gsk-test",
        )
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            from src.llm.groq_provider import GroqProvider
            provider = GroqProvider(config=config)
            provider._openai_embed_client = None

            with pytest.raises(RuntimeError, match="OpenAI API key"):
                await provider.embed("test")


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------


class TestGeminiProvider:
    """Tests for the Gemini provider."""

    def test_uses_gemini_base_url(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            from src.llm.gemini_provider import GeminiProvider, GEMINI_BASE_URL
            GeminiProvider(config=llm_config)

            call_args = MockClient.call_args_list[0]
            assert call_args.kwargs.get("base_url") == GEMINI_BASE_URL

    def test_uses_gemini_api_key(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI") as MockClient:
            from src.llm.gemini_provider import GeminiProvider
            GeminiProvider(config=llm_config)

            call_args = MockClient.call_args_list[0]
            assert call_args.kwargs.get("api_key") == "ai-test-gemini"

    def test_uses_default_gemini_model(self, llm_config):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            from src.llm.gemini_provider import GeminiProvider, GEMINI_DEFAULT_MODEL
            provider = GeminiProvider(config=llm_config)

            assert provider._model == GEMINI_DEFAULT_MODEL

    @pytest.mark.asyncio
    async def test_embed_uses_openai_fallback(self, llm_config, mock_embed_response):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            from src.llm.gemini_provider import GeminiProvider
            provider = GeminiProvider(config=llm_config)

            mock_oai = AsyncMock()
            mock_oai.embeddings.create = AsyncMock(return_value=mock_embed_response)
            provider._openai_embed_client = mock_oai

            result = await provider.embed("test")

            assert len(result) == 1536


# ---------------------------------------------------------------------------
# LLMManager
# ---------------------------------------------------------------------------


class TestLLMManager:
    """Tests for the LLM Manager (orchestrator)."""

    def _make_mock_provider(self, name: str = "mock", content: str = "response") -> MagicMock:
        """Create a mock LLMProvider."""
        provider = AsyncMock()
        provider.chat.return_value = {
            "role": "assistant",
            "content": content,
            "tool_calls": [],
            "finish_reason": "stop",
        }
        provider.embed.return_value = [0.1] * 1536
        provider.close.return_value = None
        return provider

    def test_init_with_valid_providers(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider("openai")
        manager = LLMManager(providers={"openai": p1}, default="openai")

        assert manager.active_name == "openai"
        assert manager.available == ["openai"]

    def test_init_fails_with_no_providers(self):
        from src.llm.llm_manager import LLMManager

        with pytest.raises(ValueError, match="At least one"):
            LLMManager(providers={}, default="openai")

    def test_init_fails_with_invalid_default(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider()
        with pytest.raises(ValueError, match="not in available"):
            LLMManager(providers={"openai": p1}, default="groq")

    def test_switch_provider(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider()
        p2 = self._make_mock_provider()
        manager = LLMManager(providers={"openai": p1, "groq": p2}, default="openai")

        result = manager.switch("groq")
        assert result == "groq"
        assert manager.active_name == "groq"

    def test_switch_with_alias(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider()
        p2 = self._make_mock_provider()
        manager = LLMManager(providers={"openai": p1, "anthropic": p2}, default="openai")

        result = manager.switch("claude")
        assert result == "anthropic"

    def test_switch_to_invalid_provider_raises(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider()
        manager = LLMManager(providers={"openai": p1}, default="openai")

        with pytest.raises(ValueError, match="not available"):
            manager.switch("nonexistent")

    @pytest.mark.asyncio
    async def test_chat_delegates_to_active(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider(content="from openai")
        p2 = self._make_mock_provider(content="from groq")
        manager = LLMManager(providers={"openai": p1, "groq": p2}, default="openai")

        result = await manager.chat(messages=[{"role": "user", "content": "hi"}])
        assert result["content"] == "from openai"

        manager.switch("groq")
        result = await manager.chat(messages=[{"role": "user", "content": "hi"}])
        assert result["content"] == "from groq"

    @pytest.mark.asyncio
    async def test_failover_on_primary_failure(self):
        from src.llm.llm_manager import LLMManager

        p_broken = AsyncMock()
        p_broken.chat.side_effect = RuntimeError("API down")
        p_broken.close.return_value = None

        p_working = self._make_mock_provider(content="fallback response")

        manager = LLMManager(
            providers={"openai": p_broken, "groq": p_working},
            default="openai",
        )

        result = await manager.chat(messages=[{"role": "user", "content": "hi"}])
        assert result["content"] == "fallback response"

    @pytest.mark.asyncio
    async def test_graceful_failure_when_all_providers_down(self):
        from src.llm.llm_manager import LLMManager

        p1 = AsyncMock()
        p1.chat.side_effect = RuntimeError("down")
        p1.close.return_value = None

        p2 = AsyncMock()
        p2.chat.side_effect = RuntimeError("also down")
        p2.close.return_value = None

        manager = LLMManager(providers={"a": p1, "b": p2}, default="a")

        result = await manager.chat(messages=[{"role": "user", "content": "hi"}])
        assert result["finish_reason"] == "error"
        assert "trouble" in result["content"]

    @pytest.mark.asyncio
    async def test_embed_delegates_to_embedding_provider(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider()
        p1.embed.return_value = [0.5] * 1536

        manager = LLMManager(
            providers={"openai": p1},
            default="openai",
            embedding_provider=p1,
        )

        result = await manager.embed("test")
        assert len(result) == 1536
        assert result[0] == 0.5

    @pytest.mark.asyncio
    async def test_embed_returns_empty_on_failure(self):
        from src.llm.llm_manager import LLMManager

        p1 = AsyncMock()
        p1.embed.side_effect = RuntimeError("embed failed")
        p1.close.return_value = None

        manager = LLMManager(
            providers={"openai": p1},
            default="openai",
            embedding_provider=p1,
        )

        result = await manager.embed("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_close_closes_all_providers(self):
        from src.llm.llm_manager import LLMManager

        p1 = self._make_mock_provider()
        p2 = self._make_mock_provider()

        manager = LLMManager(providers={"openai": p1, "groq": p2}, default="openai")
        await manager.close()

        p1.close.assert_awaited_once()
        p2.close.assert_awaited_once()

    def test_available_lists_all_providers(self):
        from src.llm.llm_manager import LLMManager

        providers = {
            "openai": self._make_mock_provider(),
            "groq": self._make_mock_provider(),
            "anthropic": self._make_mock_provider(),
            "gemini": self._make_mock_provider(),
        }
        manager = LLMManager(providers=providers, default="openai")

        assert set(manager.available) == {"openai", "groq", "anthropic", "gemini"}

    @pytest.mark.asyncio
    async def test_failover_tries_all_in_order(self):
        """Verify failover tries active first, then rest sequentially."""
        from src.llm.llm_manager import LLMManager

        call_order = []

        async def fail_chat(**kwargs):
            call_order.append("a")
            raise RuntimeError("fail")

        async def fail_chat_b(**kwargs):
            call_order.append("b")
            raise RuntimeError("fail")

        async def succeed_chat(**kwargs):
            call_order.append("c")
            return {"role": "assistant", "content": "ok", "tool_calls": [], "finish_reason": "stop"}

        pa = AsyncMock()
        pa.chat.side_effect = fail_chat
        pa.close.return_value = None

        pb = AsyncMock()
        pb.chat.side_effect = fail_chat_b
        pb.close.return_value = None

        pc = AsyncMock()
        pc.chat.side_effect = succeed_chat
        pc.close.return_value = None

        manager = LLMManager(providers={"a": pa, "b": pb, "c": pc}, default="a")
        result = await manager.chat(messages=[{"role": "user", "content": "hi"}])

        assert result["content"] == "ok"
        assert call_order == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Config: new provider fields
# ---------------------------------------------------------------------------


class TestLLMConfigProviders:
    """Test that LLMConfig accepts new provider values and keys."""

    def test_groq_provider_accepted(self):
        config = LLMConfig(provider="groq", api_key="test", groq_api_key="gsk-test")
        assert config.provider == "groq"

    def test_gemini_provider_accepted(self):
        config = LLMConfig(provider="gemini", api_key="test", gemini_api_key="ai-test")
        assert config.provider == "gemini"

    def test_invalid_provider_rejected(self):
        with pytest.raises(ValueError, match="provider"):
            LLMConfig(provider="mistral", api_key="test")

    def test_extra_keys_default_to_empty(self):
        config = LLMConfig(provider="openai", api_key="test")
        assert config.groq_api_key == ""
        assert config.gemini_api_key == ""
        assert config.anthropic_api_key == ""
