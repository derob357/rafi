"""Twilio voice call handling: webhooks and outbound calls."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from twilio.rest import Client as TwilioClient
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse, Connect

from src.security.auth import verify_twilio_signature

if TYPE_CHECKING:
    from src.db.supabase_client import SupabaseClient
    from src.tools.tool_registry import ToolRegistry
    from src.voice.elevenlabs_agent import ElevenLabsAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/twilio")


class TwilioHandler:
    """Manages Twilio voice calls: inbound webhooks and outbound initiation."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        phone_number: str,
        client_phone: str,
        elevenlabs_agent_id: Optional[str] = None,
        webhook_base_url: str = "",
        tool_registry: Optional[ToolRegistry] = None,
        elevenlabs_agent: Optional[ElevenLabsAgent] = None,
        db: Optional[SupabaseClient] = None,
        telegram_send_func: Optional[Callable] = None,
    ) -> None:
        if not account_sid or not auth_token:
            raise ValueError("Twilio account_sid and auth_token are required")
        if not phone_number:
            raise ValueError("Twilio phone_number is required")
        if not client_phone:
            raise ValueError("Client phone number is required")

        self._account_sid = account_sid
        self._auth_token = auth_token
        self._phone_number = phone_number
        self._client_phone = client_phone
        self._elevenlabs_agent_id = elevenlabs_agent_id
        self._webhook_base_url = webhook_base_url
        self._tool_registry = tool_registry
        self._elevenlabs_agent = elevenlabs_agent
        self._db = db
        self._telegram_send = telegram_send_func
        self._client = TwilioClient(account_sid, auth_token)
        self._validator = RequestValidator(auth_token)
        # Track active calls for transcript retrieval
        self._active_calls: dict[str, dict[str, Any]] = {}

    @property
    def twilio_client(self) -> TwilioClient:
        return self._client

    def set_agent_id(self, agent_id: str) -> None:
        """Set the ElevenLabs agent ID for call connections."""
        self._elevenlabs_agent_id = agent_id

    def set_tool_registry(self, tool_registry: ToolRegistry) -> None:
        """Set the tool registry for voice tool call dispatch."""
        self._tool_registry = tool_registry

    def set_elevenlabs_agent(self, agent: ElevenLabsAgent) -> None:
        """Set the ElevenLabs agent for transcript retrieval."""
        self._elevenlabs_agent = agent

    def set_db(self, db: SupabaseClient) -> None:
        """Set the database client for call log storage."""
        self._db = db

    def set_telegram_send(self, func: Callable) -> None:
        """Set the Telegram send function for call summaries."""
        self._telegram_send = func

    async def handle_inbound_call(self, request: Request) -> Response:
        """Handle an inbound Twilio voice call webhook.

        Validates the request signature, then connects to ElevenLabs agent.
        """
        if not await verify_twilio_signature(request, self._auth_token):
            logger.warning("Invalid Twilio signature on inbound call")
            return Response(status_code=403, content="Forbidden")

        form_data = await request.form()
        call_sid = form_data.get("CallSid", "unknown")
        from_number = form_data.get("From", "unknown")
        logger.info("Inbound call from %s (SID: %s)", from_number, call_sid)

        self._active_calls[call_sid] = {"direction": "inbound", "from": from_number}

        twiml = VoiceResponse()

        if not self._elevenlabs_agent_id:
            logger.error("No ElevenLabs agent ID configured for call handling")
            twiml.say("I'm sorry, the assistant is not available right now. Please try again later.")
            return Response(
                content=str(twiml),
                media_type="application/xml",
            )

        connect = Connect()
        connect.conversation_relay(
            url=f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={self._elevenlabs_agent_id}",
        )
        twiml.append(connect)

        return Response(
            content=str(twiml),
            media_type="application/xml",
        )

    async def handle_call_status(self, request: Request) -> Response:
        """Handle Twilio call status callback.

        On call completion, attempts to store the call log in Supabase
        and send a summary to Telegram.
        """
        if not await verify_twilio_signature(request, self._auth_token):
            logger.warning("Invalid Twilio signature on status callback")
            return Response(status_code=403, content="Forbidden")

        form_data = await request.form()
        call_sid = form_data.get("CallSid", "unknown")
        call_status = form_data.get("CallStatus", "unknown")
        duration = form_data.get("CallDuration", "0")

        logger.info(
            "Call status update - SID: %s, Status: %s, Duration: %ss",
            call_sid,
            call_status,
            duration,
        )

        # On call completion, store the call log and notify via Telegram
        if call_status == "completed" and call_sid != "unknown":
            await self._handle_call_completed(call_sid, int(duration or 0))

        # Clean up call tracking
        self._active_calls.pop(call_sid, None)

        return Response(status_code=200, content="OK")

    async def _handle_call_completed(self, call_sid: str, duration_seconds: int) -> None:
        """Process a completed call: store log and send summary."""
        call_info = self._active_calls.get(call_sid, {})
        direction = call_info.get("direction", "unknown")

        # Store call log in Supabase
        if self._db:
            try:
                await self._db.insert("call_logs", {
                    "call_sid": call_sid,
                    "direction": direction,
                    "duration_seconds": duration_seconds,
                    "transcript": "",  # Transcript retrieval requires conversation_id mapping
                    "summary": f"{direction.title()} call completed ({duration_seconds}s)",
                })
                logger.info("Call log stored for SID: %s", call_sid)
            except Exception as e:
                logger.error("Failed to store call log for %s: %s", call_sid, str(e))

        # Send summary to Telegram
        if self._telegram_send and callable(self._telegram_send):
            try:
                summary = (
                    f"Call completed ({direction}, {duration_seconds}s). "
                    f"Call SID: {call_sid}"
                )
                await self._telegram_send(summary)
            except Exception as e:
                logger.error("Failed to send call summary to Telegram: %s", str(e))

    async def initiate_outbound_call(
        self,
        context: Optional[str] = None,
    ) -> Optional[str]:
        """Initiate an outbound call to the client.

        Args:
            context: Optional context to pass to the call (e.g., briefing content).

        Returns:
            Call SID if successful, None otherwise.
        """
        if not self._elevenlabs_agent_id:
            logger.error("No ElevenLabs agent ID configured for outbound calls")
            return None

        try:
            status_callback_url = (
                f"{self._webhook_base_url}/api/twilio/status"
                if self._webhook_base_url
                else None
            )

            twiml = VoiceResponse()

            # Speak the briefing/reminder content before connecting to the
            # interactive ElevenLabs agent for follow-up conversation.
            if context:
                twiml.say(context, voice="Polly.Matthew")
                twiml.pause(length=1)

            connect = Connect()
            connect.conversation_relay(
                url=f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={self._elevenlabs_agent_id}",
            )
            twiml.append(connect)

            call_kwargs: dict[str, Any] = {
                "to": self._client_phone,
                "from_": self._phone_number,
                "twiml": str(twiml),
            }

            if status_callback_url:
                call_kwargs["status_callback"] = status_callback_url
                call_kwargs["status_callback_event"] = ["completed", "failed", "no-answer"]

            call = self._client.calls.create(**call_kwargs)

            logger.info(
                "Outbound call initiated - SID: %s, To: %s",
                call.sid,
                self._client_phone,
            )
            self._active_calls[call.sid] = {
                "direction": "outbound",
                "context": context,
            }
            return call.sid

        except Exception as e:
            logger.error("Failed to initiate outbound call: %s", str(e))
            return None

    async def handle_tool_call(self, request: Request) -> Response:
        """Handle a tool call webhook from ElevenLabs during a conversation.

        This endpoint receives tool calls from the ElevenLabs agent and
        executes the corresponding service function via the ToolRegistry.
        """
        try:
            body = await request.json()
            tool_name = body.get("tool_name", "")
            tool_params = body.get("parameters", {})

            logger.info("Tool call received: %s with params: %s", tool_name, tool_params)

            if not self._tool_registry:
                logger.warning("No tool registry configured for voice tool calls")
                return Response(
                    content=json.dumps({"error": "Tool execution not available"}),
                    media_type="application/json",
                )

            result = await self._tool_registry.invoke(tool_name, **tool_params)

            logger.info("Tool %s result: %s", tool_name, result[:200] if result else "empty")
            return Response(
                content=json.dumps({"result": result}),
                media_type="application/json",
            )

        except Exception as e:
            logger.error("Error handling tool call: %s", str(e))
            return Response(
                content=json.dumps({"error": f"Tool execution failed: {str(e)[:200]}"}),
                media_type="application/json",
                status_code=500,
            )
