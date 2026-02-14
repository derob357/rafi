"""Tool registry with dynamic dispatch and OpenAI schema support.

Registers tools with their implementations and LLM schemas, providing a single
entry point for tool execution across all channels (Telegram, WhatsApp, etc.)
and the voice pipeline.
"""

import inspect
import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry of executable tools for Rafi.

    Each tool has a function, description, and optional OpenAI-format schema.
    Provides dynamic dispatch: call invoke(name, **kwargs) to execute any
    registered tool and get a string result back for the LLM.
    """

    def __init__(self, registry=None):
        self.registry = registry
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a tool.

        Args:
            name: Tool name (must match the function name in the OpenAI schema).
            func: Async or sync callable to execute.
            description: Human-readable description.
            schema: Optional OpenAI-format tool schema for LLM function calling.
        """
        self._tools[name] = {
            "func": func,
            "description": description,
            "schema": schema,
        }
        logger.debug("Registered tool: %s", name)

    async def invoke(self, name: str, **kwargs: Any) -> str:
        """Execute a tool by name and return the result as a string.

        All results are converted to strings for LLM consumption.
        Non-string results are serialized to JSON.

        Args:
            name: Tool name.
            **kwargs: Tool arguments from the LLM.

        Returns:
            String result suitable for the LLM tool response.
        """
        if name not in self._tools:
            logger.warning("Unknown tool: %s", name)
            return f"Unknown tool: {name}"

        tool = self._tools[name]
        logger.info("Invoking tool: %s", name)

        try:
            if inspect.iscoroutinefunction(tool["func"]):
                result = await tool["func"](**kwargs)
            else:
                result = tool["func"](**kwargs)

            if self.registry and hasattr(self.registry, "broadcast_tool_result"):
                await self.registry.broadcast_tool_result(name, result)

            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)

        except Exception as e:
            logger.error("Tool execution error (%s): %s", name, e)
            error_msg = f"Error executing {name}: {str(e)[:200]}"
            if self.registry and hasattr(self.registry, "broadcast_tool_result"):
                await self.registry.broadcast_tool_result(name, {"error": str(e)})
            return error_msg

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Return OpenAI-format tool schemas for all registered tools.

        Only returns schemas for tools that have one registered.
        """
        return [
            tool["schema"]
            for tool in self._tools.values()
            if tool.get("schema")
        ]

    def get_tool_definitions(self) -> List[Dict[str, str]]:
        """Return simple metadata for all registered tools."""
        return [
            {"name": name, "description": tool["description"]}
            for name, tool in self._tools.items()
        ]

    @property
    def tool_names(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._tools.keys())
