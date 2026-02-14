"""WhatsApp channel adapter via Twilio WhatsApp API.

Inbound messages arrive via FastAPI webhook. Outbound messages
are sent via the Twilio REST API. Implements ChannelAdapter so
the ChannelManager can start/stop it alongside Telegram.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from src.channels.base import ChannelAdapter, ChannelMessage
from src.channels.processor import MessageProcessor
from src.config.loader import AppConfig

logger = logging.getLogger(__name__)


class WhatsAppAdapter(ChannelAdapter):
    """WhatsApp adapter backed by Twilio WhatsApp Business API."""

    channel_id = "whatsapp"

    def __init__(
        self,
        config: AppConfig,
        processor: MessageProcessor,
    ) -> None:
        self._config = config
        self._processor = processor
        self._twilio_client: Any = None

    def is_configured(self) -> bool:
        return bool(
            self._config.twilio.account_sid
            and self._config.twilio.auth_token
            and self._config.twilio.phone_number
        )

    async def start(self) -> None:
        """Initialize the Twilio client for outbound messaging.

        Inbound messages are handled by FastAPI webhook routes,
        not by a long-running poll/socket.
        """
        if not self.is_configured():
            logger.info("WhatsApp adapter not configured, skipping")
            return

        try:
            from twilio.rest import Client
            self._twilio_client = Client(
                self._config.twilio.account_sid,
                self._config.twilio.auth_token,
            )
            logger.info("WhatsApp adapter started (webhook-based)")
        except ImportError:
            logger.warning("twilio package not installed, WhatsApp adapter disabled")
        except Exception as e:
            logger.error("Failed to initialize WhatsApp adapter: %s", e)

    async def stop(self) -> None:
        self._twilio_client = None
        logger.info("WhatsApp adapter stopped")

    async def send_text(self, to: str, text: str, **kwargs: Any) -> dict:
        if not self._twilio_client:
            return {"error": "WhatsApp adapter not initialized"}

        try:
            from_number = f"whatsapp:{self._config.twilio.phone_number}"
            to_number = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to

            message = self._twilio_client.messages.create(
                from_=from_number,
                to=to_number,
                body=text,
            )
            return {"sid": message.sid, "status": message.status}
        except Exception as e:
            logger.error("Failed to send WhatsApp message: %s", e)
            return {"error": str(e)}

    async def send_media(
        self, to: str, text: str, media_url: str, **kwargs: Any
    ) -> dict:
        if not self._twilio_client:
            return {"error": "WhatsApp adapter not initialized"}

        try:
            from_number = f"whatsapp:{self._config.twilio.phone_number}"
            to_number = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to

            message = self._twilio_client.messages.create(
                from_=from_number,
                to=to_number,
                body=text,
                media_url=[media_url],
            )
            return {"sid": message.sid, "status": message.status}
        except Exception as e:
            logger.error("Failed to send WhatsApp media: %s", e)
            return {"error": str(e)}

    async def send_proactive(self, text: str) -> None:
        """Send a proactive message to the configured client phone."""
        await self.send_text(to=self._config.twilio.client_phone, text=text)

    # -- Webhook processing --------------------------------------------------

    async def handle_inbound(self, form_data: dict[str, str]) -> str:
        """Process an inbound WhatsApp message from a Twilio webhook.

        Args:
            form_data: Parsed form body from the Twilio POST request.

        Returns:
            TwiML response string (empty — we reply via REST, not TwiML).
        """
        body = form_data.get("Body", "").strip()
        sender = form_data.get("From", "").replace("whatsapp:", "")
        media_url = form_data.get("MediaUrl0")

        if not body and not media_url:
            return "<Response></Response>"

        msg = ChannelMessage(
            channel="whatsapp",
            sender_id=sender,
            text=body,
            media_url=media_url,
            timestamp=datetime.utcnow(),
            raw=form_data,
        )

        response_text = await self._processor.process(msg)

        # Send reply via REST API (more reliable than TwiML for long responses)
        await self.send_text(to=sender, text=response_text)

        return "<Response></Response>"
