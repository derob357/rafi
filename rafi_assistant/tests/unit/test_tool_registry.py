import pytest
from unittest.mock import AsyncMock, MagicMock
from src.tools.tool_registry import ToolRegistry

@pytest.mark.asyncio
async def test_tool_registration():
    """Test tool registration and metadata retrieval."""
    registry = MagicMock()
    tool_reg = ToolRegistry(registry)
    
    def my_tool(x): return x * 2
    tool_reg.register_tool("double", my_tool, "Doubles a number")
    
    defs = tool_reg.get_tool_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "double"
    assert defs[0]["description"] == "Doubles a number"

@pytest.mark.asyncio
async def test_tool_invocation_sync():
    """Test invoking a synchronous tool."""
    registry = MagicMock()
    registry.broadcast_tool_result = AsyncMock()
    tool_reg = ToolRegistry(registry)
    
    mock_func = MagicMock(return_value=42)
    tool_reg.register_tool("test", mock_func, "desc")
    
    result = await tool_reg.invoke("test", 1, 2)
    
    assert result == 42
    mock_func.assert_called_once_with(1, 2)
    registry.broadcast_tool_result.assert_called_once_with("test", 42)

@pytest.mark.asyncio
async def test_tool_invocation_async():
    """Test invoking an asynchronous tool."""
    registry = MagicMock()
    registry.broadcast_tool_result = AsyncMock()
    tool_reg = ToolRegistry(registry)
    
    mock_func = AsyncMock(return_value="async-result")
    tool_reg.register_tool("async_test", mock_func, "desc")
    
    result = await tool_reg.invoke("async_test")
    
    assert result == "async-result"
    registry.broadcast_tool_result.assert_called_once_with("async_test", "async-result")

@pytest.mark.asyncio
async def test_tool_invocation_error():
    """Test error handling during tool invocation."""
    registry = MagicMock()
    registry.broadcast_tool_result = AsyncMock()
    tool_reg = ToolRegistry(registry)
    
    def failing_tool(): raise ValueError("Boom")
    tool_reg.register_tool("fail", failing_tool, "desc")
    
    result = await tool_reg.invoke("fail")
    
    assert "error" in result
    assert "Boom" in result["error"]
    registry.broadcast_tool_result.assert_called_once()
    call_args = registry.broadcast_tool_result.call_args
    assert call_args[0][0] == "fail"
    assert "Boom" in call_args[0][1]["error"]
