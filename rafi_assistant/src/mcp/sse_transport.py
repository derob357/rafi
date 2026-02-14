"""MCP SSE transport for remote access.

Exposes the MCP server over HTTP using Server-Sent Events (SSE),
allowing remote Claude Code instances to access Rafi's tools through
a Cloudflare tunnel.

Protocol:
  GET  /api/mcp/sse       → SSE stream (session creation + response delivery)
  POST /api/mcp/messages   → Send JSON-RPC messages to a session
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.mcp.server import MCPServer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# LiveMCPServer — subclass that uses live app services for 3 stub tools
# ---------------------------------------------------------------------------


class LiveMCPServer(MCPServer):
    """MCPServer subclass that delegates to live Rafi services.

    Overrides the three tools that are stubs in the base class
    (calendar, feedback, send_message) to use real services from
    ``app.state``.
    """

    def __init__(self, app_state: Any) -> None:
        super().__init__()
        self._app_state = app_state

    async def _execute_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> str:
        if name == "rafi_get_calendar":
            return await self._live_calendar(arguments)
        elif name == "rafi_get_feedback_summary":
            return await self._live_feedback(arguments)
        elif name == "rafi_send_message":
            return await self._live_send_message(arguments)
        else:
            return await super()._execute_tool(name, arguments)

    async def _live_calendar(self, arguments: dict[str, Any]) -> str:
        calendar = getattr(self._app_state, "calendar", None)
        if calendar is None:
            return "Calendar service not available."
        days = arguments.get("days", 7)
        try:
            events = await calendar.list_events(days_ahead=days)
            if not events:
                return "No upcoming events."
            lines = []
            for ev in events:
                start = ev.get("start", "")
                summary = ev.get("summary", "(no title)")
                lines.append(f"- {start}: {summary}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching calendar: {e}"

    async def _live_feedback(self, arguments: dict[str, Any]) -> str:
        db = getattr(self._app_state, "db", None)
        if db is None:
            return "Database not available."
        days = arguments.get("days", 7)
        try:
            result = db.table("feedback").select("*").gte(
                "created_at",
                f"now() - interval '{days} days'",
            ).order("created_at", desc=True).limit(20).execute()
            rows = result.data if result.data else []
            if not rows:
                return f"No feedback in the last {days} days."
            lines = [
                f"- [{r.get('created_at', '?')[:10]}] "
                f"rating={r.get('rating', '?')} {r.get('comment', '')}"
                for r in rows
            ]
            return f"Feedback ({len(rows)} entries, last {days} days):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error fetching feedback: {e}"

    async def _live_send_message(self, arguments: dict[str, Any]) -> str:
        channel_manager = getattr(self._app_state, "channel_manager", None)
        if channel_manager is None:
            return "Channel manager not available."
        message = arguments.get("message", "")
        if not message:
            return "No message provided."
        try:
            await channel_manager.send_to_preferred(message)
            return f"Message sent successfully ({len(message)} chars)."
        except Exception as e:
            return f"Error sending message: {e}"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

MAX_SESSIONS = 50
SESSION_TTL_SECONDS = 3600  # 1 hour


@dataclass
class SSESession:
    session_id: str
    server: MCPServer
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SSESession] = {}

    def create(self, app_state: Any) -> SSESession:
        self._cleanup_stale()
        session_id = uuid.uuid4().hex
        server = LiveMCPServer(app_state)
        session = SSESession(session_id=session_id, server=server)
        self._sessions[session_id] = session
        logger.info("MCP SSE session created: %s", session_id[:8])
        return session

    def get(self, session_id: str) -> SSESession | None:
        session = self._sessions.get(session_id)
        if session:
            session.last_activity = time.time()
        return session

    def remove(self, session_id: str) -> None:
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info("MCP SSE session removed: %s", session_id[:8])

    def _cleanup_stale(self) -> None:
        now = time.time()
        stale = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_activity > SESSION_TTL_SECONDS
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
            logger.info("MCP SSE session expired: %s", sid[:8])

        # Evict oldest if over capacity
        while len(self._sessions) >= MAX_SESSIONS:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_activity)
            self._sessions.pop(oldest_id)
            logger.warning("MCP SSE session evicted (capacity): %s", oldest_id[:8])

    @property
    def active_count(self) -> int:
        return len(self._sessions)


_session_manager = SessionManager()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def verify_mcp_token(request: Request) -> None:
    """FastAPI dependency that checks Bearer token against MCP_AUTH_TOKEN env var.

    If MCP_AUTH_TOKEN is not set, auth is disabled (local dev mode).
    """
    expected = os.environ.get("MCP_AUTH_TOKEN", "")
    if not expected:
        return  # Auth disabled

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth_header[7:]  # len("Bearer ") == 7
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

KEEPALIVE_TIMEOUT = 30  # seconds


@router.get("/sse", dependencies=[Depends(verify_mcp_token)])
async def sse_endpoint(request: Request) -> StreamingResponse:
    """Create an SSE session and stream responses back to the client."""
    session = _session_manager.create(request.app.state)

    base_url = str(request.url_for("mcp_messages"))
    # Respect X-Forwarded-Proto from reverse proxies (e.g. Cloudflare tunnel)
    if request.headers.get("x-forwarded-proto") == "https" and base_url.startswith("http://"):
        base_url = "https://" + base_url[7:]
    post_url = base_url + f"?sessionId={session.session_id}"

    async def event_stream():
        try:
            # First event: tell client where to POST
            yield f"event: endpoint\ndata: {post_url}\n\n"

            while True:
                try:
                    msg = await asyncio.wait_for(
                        session.queue.get(), timeout=KEEPALIVE_TIMEOUT
                    )
                    data = json.dumps(msg)
                    yield f"event: message\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive comment to prevent Cloudflare idle disconnect
                    yield ": keepalive\n\n"

                # Check if client disconnected
                if await request.is_disconnected():
                    break
        finally:
            _session_manager.remove(session.session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Message endpoint
# ---------------------------------------------------------------------------


@router.post("/messages", name="mcp_messages", dependencies=[Depends(verify_mcp_token)])
async def messages_endpoint(
    request: Request,
    sessionId: str = Query(..., description="Session ID from SSE endpoint event"),
) -> dict[str, str]:
    """Receive a JSON-RPC message and route it to the correct session."""
    session = _session_manager.get(sessionId)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    response = await session.server.handle_message(body)

    if response is not None:
        await session.queue.put(response)

    return {"status": "accepted"}
