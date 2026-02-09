import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.voice.conversation_manager import ConversationManager

@pytest.mark.asyncio
async def test_conversation_manager_start_stop():
    """Test starting and stopping the conversation manager."""
    registry = MagicMock()
    # Mocking broadcast_transcript instead of emit because it's used in the loop
    registry.broadcast_transcript = AsyncMock()
    registry.emit = AsyncMock()
    
    manager = ConversationManager(registry)
    
    await manager.start_listening()
    assert manager._is_listening is True
    assert manager._listening_task is not None
    
    await manager.stop_listening()
    assert manager._is_listening is False
    assert manager._listening_task is None

@pytest.mark.asyncio
async def test_conversation_manager_speak():
    """Test the speak method emits voice events."""
    registry = MagicMock()
    registry.emit = AsyncMock()
    
    manager = ConversationManager(registry)
    await manager.speak("Hello")
    
    # One for 'speaking', one for 'idle'
    assert registry.emit.call_count == 2
    registry.emit.assert_any_call("voice", status="speaking", text="Hello")
    registry.emit.assert_any_call("voice", status="idle")
