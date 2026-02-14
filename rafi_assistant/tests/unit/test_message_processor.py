"""Unit tests for MessageProcessor orchestration and guardrails."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.channels.base import ChannelMessage
from src.channels import processor as processor_module
from src.channels.processor import MessageProcessor


@pytest.fixture
def base_message() -> ChannelMessage:
    return ChannelMessage(channel="telegram", sender_id="user-1", text="hello")


@pytest.fixture
def memory_mock() -> MagicMock:
    mock = MagicMock()
    mock.store_message = AsyncMock()
    mock.get_context_messages = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def tool_registry_mock() -> MagicMock:
    mock = MagicMock()
    mock.get_openai_schemas.return_value = [{"type": "function", "function": {"name": "sample"}}]
    mock.invoke = AsyncMock(return_value="tool-result")
    return mock


@pytest.fixture
def llm_mock() -> MagicMock:
    mock = MagicMock()
    mock.chat = AsyncMock(return_value={"content": "ok", "tool_calls": []})
    return mock


@pytest.fixture
def memory_files_mock() -> MagicMock:
    mock = MagicMock()
    mock.build_system_prompt.return_value = "system prompt from files"
    return mock


@pytest.mark.asyncio
async def test_process_returns_fallback_for_empty_sanitized_input(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: "")
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: False)

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "I didn't catch that. Could you try again?"
    memory_mock.store_message.assert_not_called()
    llm_mock.chat.assert_not_called()


@pytest.mark.asyncio
async def test_process_blocks_prompt_injection(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: "clean")
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: True)

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "I can't process that message."
    memory_mock.store_message.assert_not_called()
    llm_mock.chat.assert_not_called()


@pytest.mark.asyncio
async def test_process_non_tool_path_stores_user_and_assistant(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: text)
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: False)
    monkeypatch.setattr(processor_module, "wrap_user_input", lambda text: text)

    llm_mock.chat = AsyncMock(return_value={"content": "assistant reply", "tool_calls": []})

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "assistant reply"
    assert memory_mock.store_message.await_count == 2
    memory_mock.store_message.assert_any_await("user", "hello", "telegram_text")
    memory_mock.store_message.assert_any_await("assistant", "assistant reply", "telegram_text")


@pytest.mark.asyncio
async def test_process_tool_call_loop_executes_tool_then_returns(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: text)
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: False)
    monkeypatch.setattr(processor_module, "wrap_user_input", lambda text: text)

    llm_mock.chat = AsyncMock(
        side_effect=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "function": {"name": "sample", "arguments": '{"value": 7}'},
                    }
                ],
            },
            {"content": "done", "tool_calls": []},
        ]
    )

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "done"
    assert llm_mock.chat.await_count == 2
    tool_registry_mock.invoke.assert_awaited_once_with("sample", value=7)


@pytest.mark.asyncio
async def test_process_tool_call_with_invalid_json_uses_empty_args(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: text)
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: False)
    monkeypatch.setattr(processor_module, "wrap_user_input", lambda text: text)

    llm_mock.chat = AsyncMock(
        side_effect=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "function": {"name": "sample", "arguments": "{not-json"},
                    }
                ],
            },
            {"content": "done", "tool_calls": []},
        ]
    )

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "done"
    tool_registry_mock.invoke.assert_awaited_once_with("sample")


@pytest.mark.asyncio
async def test_process_returns_graceful_error_when_llm_raises(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: text)
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: False)
    monkeypatch.setattr(processor_module, "wrap_user_input", lambda text: text)

    llm_mock.chat = AsyncMock(side_effect=RuntimeError("provider down"))

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "I'm having trouble thinking right now, please try again in a moment."


@pytest.mark.asyncio
async def test_process_returns_last_content_when_max_tool_rounds_exhausted(
    mock_config,
    base_message,
    memory_mock,
    tool_registry_mock,
    llm_mock,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processor_module, "sanitize_text", lambda text, max_length=4096: text)
    monkeypatch.setattr(processor_module, "detect_prompt_injection", lambda text: False)
    monkeypatch.setattr(processor_module, "wrap_user_input", lambda text: text)

    tool_call_response = {
        "content": "intermediate",
        "tool_calls": [
            {
                "id": "tc_x",
                "function": {"name": "sample", "arguments": "{}"},
            }
        ],
    }
    llm_mock.chat = AsyncMock(return_value=tool_call_response)

    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    result = await processor.process(base_message)

    assert result == "intermediate"
    assert llm_mock.chat.await_count == 5
    assert memory_mock.store_message.await_count == 2


def test_build_system_prompt_uses_memory_files_when_available(mock_config, memory_mock, tool_registry_mock, llm_mock, memory_files_mock):
    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
        memory_files=memory_files_mock,
    )

    prompt = processor._build_system_prompt()

    assert prompt == "system prompt from files"
    memory_files_mock.build_system_prompt.assert_called_once()


def test_build_system_prompt_falls_back_without_memory_files(mock_config, memory_mock, tool_registry_mock, llm_mock):
    processor = MessageProcessor(
        config=mock_config,
        llm=llm_mock,
        memory=memory_mock,
        tool_registry=tool_registry_mock,
    )

    prompt = processor._build_system_prompt()

    assert mock_config.elevenlabs.agent_name in prompt
    assert mock_config.client.name in prompt
    assert "Always confirm before sending emails" in prompt
