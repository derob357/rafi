"""Channel adapter interface and normalized message type.

All messaging platforms (Telegram, WhatsApp, Slack, Discord) implement
the ChannelAdapter ABC. Messages are normalized into ChannelMessage objects
so the MessageProcessor can handle them uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class ChannelMessage:
    """Normalized message across all platforms."""

    channel: str  # "telegram", "whatsapp", "slack", "discord"
    sender_id: str
    text: str
    media_url: Optional[str] = None
    thread_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: Any = None  # platform-specific original payload


class ChannelAdapter(ABC):
    """Base interface all channel adapters implement.

    Subclasses handle platform-specific connection logic (polling,
    webhooks, websockets) while exposing a uniform send/receive API.
    """

    channel_id: str = ""

    def is_configured(self) -> bool:
        """Return True if required credentials/config are present."""
        return True

    @abstractmethod
    async def start(self) -> None:
        """Start listening for inbound messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the adapter."""

    @abstractmethod
    async def send_text(self, to: str, text: str, **kwargs: Any) -> dict:
        """Send a text message.

        Args:
            to: Recipient identifier (chat_id, phone number, etc.).
            text: Message body.

        Returns:
            Platform-specific delivery receipt / metadata.
        """

    @abstractmethod
    async def send_media(
        self, to: str, text: str, media_url: str, **kwargs: Any
    ) -> dict:
        """Send a message with media attachment.

        Args:
            to: Recipient identifier.
            text: Caption / body text.
            media_url: URL of the media file.

        Returns:
            Platform-specific delivery receipt / metadata.
        """
