"""Slack channel adapter stub.

Placeholder implementation. Fill in Socket Mode or Events API
logic to make Slack fully functional.
"""

from __future__ import annotations

import logging
from typing import Any

from src.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack adapter stub — not yet implemented."""

    channel_id = "slack"

    def is_configured(self) -> bool:
        return False

    async def start(self) -> None:
        raise NotImplementedError("Slack adapter not yet implemented")

    async def stop(self) -> None:
        pass

    async def send_text(self, to: str, text: str, **kwargs: Any) -> dict:
        raise NotImplementedError("Slack adapter not yet implemented")

    async def send_media(
        self, to: str, text: str, media_url: str, **kwargs: Any
    ) -> dict:
        raise NotImplementedError("Slack adapter not yet implemented")
