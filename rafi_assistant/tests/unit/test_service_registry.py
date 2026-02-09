import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.orchestration.service_registry import ServiceRegistry

@pytest.mark.asyncio
async def test_service_registry_registration():
    """Test that services can be registered and retrieved."""
    db = MagicMock()
    llm = MagicMock()
    registry = ServiceRegistry(db=db, llm=llm)
    
    assert registry.db == db
    assert registry.llm == llm
    assert registry.calendar is None

@pytest.mark.asyncio
async def test_service_registry_listeners():
    """Test that listeners are notified when an event is emitted."""
    registry = ServiceRegistry()
    mock_callback = AsyncMock()
    
    registry.register_listener("voice", mock_callback)
    await registry.emit("voice", status="listening")
    
    mock_callback.assert_called_once_with(status="listening")

@pytest.mark.asyncio
async def test_service_registry_broadcast_transcript():
    """Test transcript broadcasting and queueing."""
    registry = ServiceRegistry()
    mock_callback = AsyncMock()
    
    registry.register_listener("transcript", mock_callback)
    await registry.broadcast_transcript("Hello world", is_final=True)
    
    # Check listener
    mock_callback.assert_called_once_with(text="Hello world", is_final=True)
    
    # Check queue
    item = await registry.transcript_queue.get()
    assert item == {"text": "Hello world", "is_final": True}

@pytest.mark.asyncio
async def test_service_registry_broadcast_tool_result():
    """Test tool result broadcasting and queueing."""
    registry = ServiceRegistry()
    mock_callback = AsyncMock()
    
    registry.register_listener("tools", mock_callback)
    await registry.broadcast_tool_result("get_weather", {"temp": 72})
    
    # Check listener
    mock_callback.assert_called_once_with(tool="get_weather", result={"temp": 72})
    
    # Check queue
    item = await registry.tool_output_queue.get()
    assert item == {"tool": "get_weather", "result": {"temp": 72}}
