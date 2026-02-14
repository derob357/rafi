"""Mobile companion WebSocket endpoint.

Provides a bidirectional channel between the mobile web UI and Rafi's
ServiceRegistry.  The client sends gesture events, voice transcriptions,
text commands, and optional camera frames; the server pushes transcript
updates, TTS audio, and visualizer state.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import time
from typing import Any, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.channels.base import ChannelMessage
from src.vision.gesture import GestureActionMapper

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Token management ──────────────────────────────────────────────────────────

_TOKEN_TTL = 3600  # 1 hour
_tokens: dict[str, dict[str, Any]] = {}


def generate_mobile_token(call_sid: str = "") -> str:
    """Create a short-lived token for mobile UI access.

    Returns:
        URL-safe token string.
    """
    token = secrets.token_urlsafe(32)
    _tokens[token] = {"created_at": time.time(), "call_sid": call_sid}

    # Prune expired tokens
    now = time.time()
    expired = [t for t, d in _tokens.items() if now - d["created_at"] > _TOKEN_TTL]
    for t in expired:
        _tokens.pop(t, None)

    return token


def _validate_token(token: str) -> bool:
    data = _tokens.get(token)
    if not data:
        return False
    if time.time() - data["created_at"] > _TOKEN_TTL:
        _tokens.pop(token, None)
        return False
    return True


# ── WebSocket endpoint ────────────────────────────────────────────────────────


@router.websocket("/ws/mobile")
async def mobile_websocket(
    websocket: WebSocket,
    t: str = Query(""),
) -> None:
    """Bidirectional WebSocket for the mobile companion UI."""

    # Validate token (skip if no tokens have been issued yet — dev mode)
    if _tokens and t and not _validate_token(t):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()

    registry = getattr(websocket.app.state, "registry", None)
    processor = getattr(websocket.app.state, "processor", None)
    send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # ── Registry listeners (forwarded to client) ──────────────────────────

    async def _on_transcript(
        text: str, is_final: bool = True, role: str = "user"
    ) -> None:
        await send_queue.put(
            {"type": "transcript", "text": text, "role": role, "is_final": is_final}
        )

    async def _on_event(event: str, data: dict) -> None:
        # Skip raw video frames (too large for mobile push)
        if event == "visual_frame":
            return
        await send_queue.put({"type": "event", "event": event, "data": data})

    if registry:
        registry.register_listener("transcript", _on_transcript)
        registry.register_listener("events", _on_event)

    try:
        await websocket.send_json({"type": "connected", "status": "ok"})

        # Two concurrent tasks: push server events, receive client messages
        async def _sender() -> None:
            while True:
                msg = await send_queue.get()
                await websocket.send_json(msg)

        async def _receiver() -> None:
            while True:
                data = await websocket.receive_json()
                await _handle_client_message(
                    data, registry, processor, websocket, send_queue
                )

        sender_task = asyncio.create_task(_sender())
        receiver_task = asyncio.create_task(_receiver())

        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        logger.info("Mobile companion disconnected")
    except Exception as exc:
        logger.error("Mobile WS error: %s", exc)
    finally:
        # Clean up listeners
        if registry:
            registry.unregister_listener("transcript", _on_transcript)
            registry.unregister_listener("events", _on_event)


# ── TTS helper ────────────────────────────────────────────────────────────────


async def _generate_tts(text: str, registry: Any) -> Optional[bytes]:
    """Generate TTS audio via ElevenLabs and return MP3 bytes."""
    agent = getattr(registry, "elevenlabs", None) if registry else None
    if not agent:
        return None
    try:
        return await agent.synthesize(text)
    except Exception as exc:
        logger.warning("TTS generation failed: %s", exc)
        return None


async def _respond_with_tts(
    response_text: str,
    registry: Any,
    send_queue: asyncio.Queue,
) -> None:
    """Send assistant transcript + TTS audio to the mobile client."""
    # Push text immediately so the user sees it while TTS generates
    await send_queue.put(
        {
            "type": "transcript",
            "text": response_text,
            "role": "assistant",
            "is_final": True,
        }
    )

    # Generate and send TTS audio
    audio_bytes = await _generate_tts(response_text, registry)
    if audio_bytes:
        await send_queue.put(
            {"type": "audio", "data": base64.b64encode(audio_bytes).decode()}
        )


# ── Client message handling ───────────────────────────────────────────────────


async def _process_user_text(
    text: str,
    registry: Any,
    processor: Any,
    send_queue: asyncio.Queue,
) -> None:
    """Run user text through MessageProcessor and reply with TTS."""
    if not text:
        return

    if processor:
        msg = ChannelMessage(channel="mobile", sender_id="mobile_user", text=text)
        try:
            response = await processor.process(msg)
        except Exception as exc:
            logger.error("MessageProcessor error: %s", exc)
            response = "Sorry, something went wrong processing your request."
        await _respond_with_tts(response, registry, send_queue)
    elif registry and registry.conversation:
        # Fallback to ConversationManager (local dev with desktop UI)
        await registry.conversation.process_text_input(text)


async def _handle_client_message(
    data: dict[str, Any],
    registry: Any,
    processor: Any,
    websocket: WebSocket,
    send_queue: asyncio.Queue,
) -> None:
    msg_type = data.get("type", "")

    if msg_type == "gesture":
        gesture = data.get("gesture", "")
        confidence = data.get("confidence", 0.0)
        logger.info("Gesture received: %s (%.0f%%)", gesture, confidence * 100)

        action = GestureActionMapper.map_gesture(gesture, confidence)
        if action:
            await websocket.send_json(
                {
                    "type": "gesture_ack",
                    "gesture": gesture,
                    "action": action["action"],
                    "label": action["label"],
                }
            )
            # If the gesture maps to a text command, process it
            if action.get("text_command"):
                await _process_user_text(
                    action["text_command"], registry, processor, send_queue
                )

    elif msg_type == "voice_text":
        # Speech-to-text result from browser Web Speech API
        text = data.get("text", "").strip()
        logger.info("Voice input: %s", text[:100])
        await _process_user_text(text, registry, processor, send_queue)

    elif msg_type == "text":
        message = data.get("message", "").strip()
        await _process_user_text(message, registry, processor, send_queue)

    elif msg_type == "frame":
        # Optional: receive camera frames from the phone for Rafi's vision
        jpeg_b64 = data.get("jpeg", "")
        if jpeg_b64 and registry:
            try:
                jpeg_bytes = base64.b64decode(jpeg_b64)
                await registry.broadcast_event(
                    "visual_frame",
                    {"mode": "remote_camera", "jpeg": jpeg_bytes, "status": "active"},
                )
            except Exception as exc:
                logger.warning("Failed to decode mobile frame: %s", exc)
