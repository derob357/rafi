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
async def test_tool_registration_with_schema():
    """Test tool registration with OpenAI schema."""
    tool_reg = ToolRegistry()
    schema = {"type": "function", "function": {"name": "greet", "parameters": {}}}

    tool_reg.register_tool("greet", lambda: "hello", "Greet user", schema=schema)

    schemas = tool_reg.get_openai_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "greet"


@pytest.mark.asyncio
async def test_tool_invocation_sync():
    """Test invoking a synchronous tool that returns a string."""
    registry = MagicMock()
    registry.broadcast_tool_result = AsyncMock()
    tool_reg = ToolRegistry(registry)

    mock_func = MagicMock(return_value="result-text")
    tool_reg.register_tool("test", mock_func, "desc")

    result = await tool_reg.invoke("test", x=1, y=2)

    assert result == "result-text"
    mock_func.assert_called_once_with(x=1, y=2)
    registry.broadcast_tool_result.assert_called_once_with("test", "result-text")


@pytest.mark.asyncio
async def test_tool_invocation_dict_serialized():
    """Test that non-string results are JSON-serialized."""
    tool_reg = ToolRegistry()

    mock_func = MagicMock(return_value={"count": 42})
    tool_reg.register_tool("test", mock_func, "desc")

    result = await tool_reg.invoke("test")

    assert '"count": 42' in result  # JSON string


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
    """Test error handling during tool invocation returns error string."""
    registry = MagicMock()
    registry.broadcast_tool_result = AsyncMock()
    tool_reg = ToolRegistry(registry)

    def failing_tool(): raise ValueError("Boom")
    tool_reg.register_tool("fail", failing_tool, "desc")

    result = await tool_reg.invoke("fail")

    assert isinstance(result, str)
    assert "Error executing fail" in result
    assert "Boom" in result


@pytest.mark.asyncio
async def test_tool_invocation_unknown():
    """Test invoking an unknown tool returns error string."""
    tool_reg = ToolRegistry()

    result = await tool_reg.invoke("nonexistent")

    assert "Unknown tool: nonexistent" in result


@pytest.mark.asyncio
async def test_tool_names_property():
    """Test the tool_names property."""
    tool_reg = ToolRegistry()

    tool_reg.register_tool("a", lambda: "", "desc")
    tool_reg.register_tool("b", lambda: "", "desc")

    assert set(tool_reg.tool_names) == {"a", "b"}


@pytest.mark.asyncio
async def test_get_openai_schemas_filters_none():
    """Test that tools without schemas are excluded from get_openai_schemas."""
    tool_reg = ToolRegistry()

    tool_reg.register_tool("with_schema", lambda: "", "desc", schema={"type": "function"})
    tool_reg.register_tool("no_schema", lambda: "", "desc")

    schemas = tool_reg.get_openai_schemas()
    assert len(schemas) == 1
