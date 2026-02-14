"""Channel manager — lifecycle and routing for all channel adapters.

Starts/stops configured adapters and provides a unified interface
for proactive messaging (heartbeat, scheduler, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


class ChannelManager:
    """Manages all channel adapter lifecycles and message routing."""

    def __init__(self, preferred_channel: str = "telegram") -> None:
        self._adapters: dict[str, ChannelAdapter] = {}
        self._preferred_channel = preferred_channel

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        self._adapters[adapter.channel_id] = adapter
        logger.debug("Registered channel adapter: %s", adapter.channel_id)

    async def start_all(self) -> None:
        """Start all configured adapters, skipping unconfigured ones."""
        for channel_id, adapter in self._adapters.items():
            if not adapter.is_configured():
                logger.info("Channel %s not configured, skipping", channel_id)
                continue
            try:
                await adapter.start()
                logger.info("Channel %s started", channel_id)
            except NotImplementedError:
                logger.info("Channel %s not yet implemented, skipping", channel_id)
            except Exception as e:
                logger.error("Failed to start channel %s: %s", channel_id, e)

    async def stop_all(self) -> None:
        """Stop all running adapters."""
        for channel_id, adapter in self._adapters.items():
            try:
                await adapter.stop()
            except Exception as e:
                logger.error("Error stopping channel %s: %s", channel_id, e)

    def get(self, channel_id: str) -> Optional[ChannelAdapter]:
        """Get an adapter by channel ID."""
        return self._adapters.get(channel_id)

    async def send_to_preferred(self, text: str) -> dict:
        """Send a message via the preferred channel.

        Falls back to any available adapter if the preferred is unavailable.
        Used by the heartbeat and scheduler for proactive notifications.
        """
        adapter = self._adapters.get(self._preferred_channel)
        if adapter and adapter.is_configured():
            if hasattr(adapter, "send_proactive"):
                await adapter.send_proactive(text)
                return {"channel": self._preferred_channel, "status": "sent"}

        # Fallback: try any configured adapter with send_proactive
        for channel_id, adapter in self._adapters.items():
            if adapter.is_configured() and hasattr(adapter, "send_proactive"):
                try:
                    await adapter.send_proactive(text)
                    return {"channel": channel_id, "status": "sent_fallback"}
                except Exception:
                    continue

        logger.error("No channel available for proactive message")
        return {"error": "no_channel_available"}

    async def send_to_channel(
        self, channel_id: str, to: str, text: str, **kwargs: Any
    ) -> dict:
        """Send a message to a specific channel.

        Args:
            channel_id: Target channel (e.g. "telegram", "whatsapp").
            to: Recipient identifier.
            text: Message body.

        Returns:
            Delivery result dict.
        """
        adapter = self._adapters.get(channel_id)
        if not adapter:
            return {"error": f"Unknown channel: {channel_id}"}
        return await adapter.send_text(to=to, text=text, **kwargs)

    @property
    def available_channels(self) -> list[str]:
        """Return list of configured channel IDs."""
        return [
            cid for cid, adapter in self._adapters.items()
            if adapter.is_configured()
        ]
