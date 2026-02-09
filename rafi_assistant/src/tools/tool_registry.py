import logging
from typing import Any, Dict, List, Callable

logger = logging.getLogger(__name__)

class ToolRegistry:
    """
    Registry of executable actions for Rafi.
    
    Tools wrap service calls (Calendar, Email, Tasks, etc.) into a consistent
    interface that can be invoked by the UI or LLM agents.
    """
    def __init__(self, registry):
        self.registry = registry
        self._tools: Dict[str, Dict[str, Any]] = {}

        # Default tools would be registered here
        # Note: We check if attributes exist to avoid crashes if services aren't initialized
        self._register_default_tools()

    def _register_default_tools(self):
        """Wire up initial tools from existing services."""
        # This is a skeleton - actual tool registration happens during wiring
        pass

    def register_tool(self, name: str, func: Callable, description: str):
        """Register a new tool."""
        self._tools[name] = {
            "func": func,
            "description": description
        }
        logger.debug(f"Registered tool: {name}")

    async def invoke(self, name: str, *args, **kwargs) -> Any:
        """Execute a tool and broadcast the result via ServiceRegistry."""
        if name not in self._tools:
            logger.error(f"Unknown tool requested: {name}")
            return {"error": f"Tool {name} not found"}
        
        logger.info(f"Invoking tool: {name}")
        tool = self._tools[name]
        
        try:
            # Check if function is coroutine
            import inspect
            if inspect.iscoroutinefunction(tool["func"]):
                result = await tool["func"](*args, **kwargs)
            else:
                result = tool["func"](*args, **kwargs)
                
            await self.registry.broadcast_tool_result(name, result)
            return result
        except Exception as e:
            logger.error(f"Error invoking tool {name}: {e}")
            await self.registry.broadcast_tool_result(name, {"error": str(e)})
            return {"error": str(e)}

    def get_tool_definitions(self) -> List[Dict[str, str]]:
        """Return metadata for all registered tools (useful for LLM prompt injection)."""
        return [
            {"name": name, "description": tool["description"]}
            for name, tool in self._tools.items()
        ]
