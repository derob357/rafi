import pytest
from unittest.mock import AsyncMock, MagicMock
from src.voice.conversation_manager import ConversationManager


@pytest.mark.asyncio
async def test_conversation_manager_speak():
    """Test the speak method emits voice events."""
    registry = MagicMock()
    registry.emit = AsyncMock()
    registry.elevenlabs = None

    manager = ConversationManager(registry)
    await manager.speak("Hello")

    # One for 'speaking', one for 'idle'
    assert registry.emit.call_count == 2
    registry.emit.assert_any_call("voice", status="speaking", text="Hello")
    registry.emit.assert_any_call("voice", status="idle")


def test_echo_normalization():
    """Normalize punctuation differences for echo checks."""
    registry = MagicMock()
    manager = ConversationManager(registry)

    manager._speech_history = ["Hello! How can I assist you today?"]
    assert manager._is_echo_text("Hello. How can I assist you today?") is True


def test_echo_rejects_low_overlap():
    """Ensure unrelated text is not flagged as echo."""
    registry = MagicMock()
    manager = ConversationManager(registry)

    manager._speech_history = ["Here is your calendar summary for today."]
    assert manager._is_echo_text("Please open my email inbox.") is False
