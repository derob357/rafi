"""Discord channel adapter stub.

Placeholder implementation. Fill in discord.py bot logic
to make Discord fully functional.
"""

from __future__ import annotations

import logging
from typing import Any

from src.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapter):
    """Discord adapter stub — not yet implemented."""

    channel_id = "discord"

    def is_configured(self) -> bool:
        return False

    async def start(self) -> None:
        raise NotImplementedError("Discord adapter not yet implemented")

    async def stop(self) -> None:
        pass

    async def send_text(self, to: str, text: str, **kwargs: Any) -> dict:
        raise NotImplementedError("Discord adapter not yet implemented")

    async def send_media(
        self, to: str, text: str, media_url: str, **kwargs: Any
    ) -> dict:
        raise NotImplementedError("Discord adapter not yet implemented")
