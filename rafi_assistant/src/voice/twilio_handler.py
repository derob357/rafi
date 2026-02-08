"""Twilio voice call handling: webhooks and outbound calls."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, Response
from twilio.rest import Client as TwilioClient
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse, Connect

from src.security.auth import verify_twilio_signature

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
        self._client = TwilioClient(account_sid, auth_token)
        self._validator = RequestValidator(auth_token)

    @property
    def twilio_client(self) -> TwilioClient:
        return self._client

    def set_agent_id(self, agent_id: str) -> None:
        """Set the ElevenLabs agent ID for call connections."""
        self._elevenlabs_agent_id = agent_id

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
        """Handle Twilio call status callback."""
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

        return Response(status_code=200, content="OK")

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
            return call.sid

        except Exception as e:
            logger.error("Failed to initiate outbound call: %s", str(e))
            return None

    async def handle_tool_call(self, request: Request) -> Response:
        """Handle a tool call webhook from ElevenLabs during a conversation.

        This endpoint receives tool calls from the ElevenLabs agent and
        executes the corresponding service function.
        """
        try:
            body = await request.json()
            tool_name = body.get("tool_name", "")
            tool_params = body.get("parameters", {})

            logger.info("Tool call received: %s with params: %s", tool_name, tool_params)

            # Tool execution is handled by the main app's tool router
            # This returns a placeholder - actual implementation wires to services
            return Response(
                content='{"status": "received"}',
                media_type="application/json",
            )

        except Exception as e:
            logger.error("Error handling tool call: %s", str(e))
            return Response(
                content='{"error": "Internal error processing tool call"}',
                media_type="application/json",
                status_code=500,
            )
