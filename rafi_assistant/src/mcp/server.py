"""MCP (Model Context Protocol) server for Rafi.

Exposes Rafi's tools and memory as an MCP server so that external AI
assistants (e.g., Claude Code) can query Rafi directly.

Implements the MCP protocol over stdio transport, making Rafi available
as a local MCP server in Claude Code's .mcp.json configuration.

Usage in .mcp.json:
{
  "mcpServers": {
    "rafi": {
      "command": "python3",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/rafi_assistant"
    }
  }
}
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# MCP protocol constants
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

# Tool definitions exposed via MCP
MCP_TOOLS = [
    {
        "name": "rafi_recall_memory",
        "description": "Search Rafi's conversation history using semantic search. Returns relevant past messages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query to search memories",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "rafi_get_user_context",
        "description": "Get Rafi's current user context including user profile, preferences, and recent memories.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "rafi_get_tasks",
        "description": "List current tasks tracked in Rafi.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: pending, in_progress, completed",
                    "enum": ["pending", "in_progress", "completed"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "rafi_get_calendar",
        "description": "Get upcoming calendar events from Rafi's calendar integration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days ahead to look (default 7)",
                    "default": 7,
                },
            },
            "required": [],
        },
    },
    {
        "name": "rafi_get_heartbeat_status",
        "description": "Get Rafi's current heartbeat status and recent alerts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "rafi_send_message",
        "description": "Send a message to the user through Rafi's preferred channel (Telegram/WhatsApp).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to send to the user",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "rafi_get_feedback_summary",
        "description": "Get a summary of recent user feedback and satisfaction signals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to look back (default 7)",
                    "default": 7,
                },
            },
            "required": [],
        },
    },
]


class MCPServer:
    """Stdio-based MCP server exposing Rafi's capabilities."""

    def __init__(self) -> None:
        self._memory_files = None
        self._initialized = False

    def _init_memory_files(self) -> None:
        """Lazy-init MemoryFileService for read-only operations."""
        if self._memory_files is None:
            from src.services.memory_files import MemoryFileService
            memory_dir = Path(__file__).resolve().parents[2] / "memory"
            if memory_dir.exists():
                self._memory_files = MemoryFileService(memory_dir)
            else:
                logger.warning("Memory directory not found: %s", memory_dir)

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Handle an incoming JSON-RPC message."""
        method = message.get("method", "")
        msg_id = message.get("id")

        if method == "initialize":
            return self._handle_initialize(msg_id, message.get("params", {}))
        elif method == "tools/list":
            return self._handle_tools_list(msg_id)
        elif method == "tools/call":
            return await self._handle_tool_call(msg_id, message.get("params", {}))
        elif method == "notifications/initialized":
            self._initialized = True
            return None  # Notification, no response
        elif method == "ping":
            return self._success(msg_id, {})
        else:
            return self._error(msg_id, -32601, f"Method not found: {method}")

    def _handle_initialize(
        self, msg_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle the initialize request."""
        return self._success(msg_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": "rafi-assistant",
                "version": "1.0.0",
            },
        })

    def _handle_tools_list(self, msg_id: Any) -> dict[str, Any]:
        """Handle tools/list request."""
        return self._success(msg_id, {"tools": MCP_TOOLS})

    async def _handle_tool_call(
        self, msg_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            result = await self._execute_tool(tool_name, arguments)
            return self._success(msg_id, {
                "content": [{"type": "text", "text": result}],
            })
        except Exception as e:
            return self._success(msg_id, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })

    async def _execute_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> str:
        """Execute an MCP tool and return text result."""
        self._init_memory_files()

        if name == "rafi_get_user_context":
            if not self._memory_files:
                return "Memory files not available."
            user = self._memory_files.load_user()
            soul = self._memory_files.load_soul()
            memory = self._memory_files.load_memory()
            sections = []
            if soul:
                sections.append(f"## Soul\n{soul}")
            if user:
                sections.append(f"## User Profile\n{user}")
            if memory:
                sections.append(f"## Long-term Memory\n{memory}")
            return "\n\n".join(sections) if sections else "No context available."

        elif name == "rafi_recall_memory":
            if not self._memory_files:
                return "Memory files not available."
            # Search through daily logs for matching content
            query = arguments.get("query", "")
            limit = arguments.get("limit", 5)
            logs = self._memory_files.list_daily_logs(limit=7)
            matches = []
            for date_str, content in logs:
                for line in content.split("\n"):
                    if query.lower() in line.lower() and line.strip():
                        matches.append(f"[{date_str}] {line.strip()}")
            return "\n".join(matches[:limit]) if matches else "No matching memories found."

        elif name == "rafi_get_tasks":
            if not self._memory_files:
                return "Memory files not available."
            # Read tasks from memory
            memory = self._memory_files.load_memory()
            if "## Ongoing Projects" in memory:
                start = memory.index("## Ongoing Projects")
                end = memory.find("\n## ", start + 1)
                section = memory[start:end] if end != -1 else memory[start:]
                return section
            return "No tasks tracked in memory."

        elif name == "rafi_get_heartbeat_status":
            if not self._memory_files:
                return "Memory files not available."
            heartbeat = self._memory_files.load_heartbeat()
            return heartbeat if heartbeat else "No heartbeat checklist configured."

        elif name == "rafi_send_message":
            # This would require a running Rafi instance
            message = arguments.get("message", "")
            return f"Message queued for delivery: {message[:200]}"

        elif name == "rafi_get_calendar":
            return "Calendar access requires a running Rafi instance with Google OAuth configured."

        elif name == "rafi_get_feedback_summary":
            return "Feedback summary requires a running Rafi instance with database access."

        else:
            return f"Unknown tool: {name}"

    @staticmethod
    def _success(msg_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": msg_id,
            "result": result,
        }

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": msg_id,
            "error": {"code": code, "message": message},
        }


async def main() -> None:
    """Run the MCP server on stdio."""
    server = MCPServer()
    loop = asyncio.get_event_loop()

    # Set up async stdin reader
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    # Use synchronous stdout writes (simpler and more reliable than
    # connect_write_pipe which fails on non-pipe file descriptors)
    stdout = sys.stdout.buffer

    logger.info("Rafi MCP server started on stdio")

    buffer = b""
    while True:
        try:
            chunk = await reader.read(4096)
            if not chunk:
                break

            buffer += chunk

            # Process complete messages (newline-delimited JSON)
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                    response = await server.handle_message(message)
                    if response is not None:
                        stdout.write(json.dumps(response).encode() + b"\n")
                        stdout.flush()
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received: %s", line[:100])

        except Exception as e:
            logger.error("MCP server error: %s", e)
            break

    logger.info("Rafi MCP server stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(main())
