"""Unit tests for channel lifecycle and routing behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.channels.base import ChannelAdapter
from src.channels.manager import ChannelManager


@dataclass
class _FakeAdapter(ChannelAdapter):
    channel_id: str
    configured: bool = True
    fail_start: bool = False
    proactive_raises: bool = False

    def __post_init__(self) -> None:
        self.started = False
        self.stopped = False
        self.sent = []
        self.proactive = []

    def is_configured(self) -> bool:
        return self.configured

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start failed")
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_text(self, to: str, text: str, **kwargs):
        self.sent.append((to, text, kwargs))
        return {"status": "sent", "to": to}

    async def send_media(self, to: str, text: str, media_url: str, **kwargs):
        return {"status": "sent_media", "to": to, "media_url": media_url}

    async def send_proactive(self, text: str):
        if self.proactive_raises:
            raise RuntimeError("proactive failed")
        self.proactive.append(text)


@pytest.mark.asyncio
async def test_start_all_skips_unconfigured_adapter() -> None:
    manager = ChannelManager(preferred_channel="telegram")
    configured = _FakeAdapter(channel_id="telegram", configured=True)
    not_configured = _FakeAdapter(channel_id="whatsapp", configured=False)
    manager.register(configured)
    manager.register(not_configured)

    await manager.start_all()

    assert configured.started is True
    assert not_configured.started is False


@pytest.mark.asyncio
async def test_start_all_continues_when_one_adapter_fails() -> None:
    manager = ChannelManager(preferred_channel="telegram")
    failing = _FakeAdapter(channel_id="telegram", fail_start=True)
    healthy = _FakeAdapter(channel_id="whatsapp")
    manager.register(failing)
    manager.register(healthy)

    await manager.start_all()

    assert healthy.started is True


@pytest.mark.asyncio
async def test_send_to_preferred_success() -> None:
    manager = ChannelManager(preferred_channel="telegram")
    preferred = _FakeAdapter(channel_id="telegram")
    manager.register(preferred)

    result = await manager.send_to_preferred("hello")

    assert result == {"channel": "telegram", "status": "sent"}
    assert preferred.proactive == ["hello"]


@pytest.mark.asyncio
async def test_send_to_preferred_fallback_when_preferred_unconfigured() -> None:
    manager = ChannelManager(preferred_channel="telegram")
    preferred = _FakeAdapter(channel_id="telegram", configured=False)
    fallback = _FakeAdapter(channel_id="whatsapp", configured=True)
    manager.register(preferred)
    manager.register(fallback)

    result = await manager.send_to_preferred("alert")

    assert result == {"channel": "whatsapp", "status": "sent_fallback"}
    assert fallback.proactive == ["alert"]


@pytest.mark.asyncio
async def test_send_to_preferred_no_channel_available() -> None:
    manager = ChannelManager(preferred_channel="telegram")
    manager.register(_FakeAdapter(channel_id="telegram", configured=False))
    manager.register(_FakeAdapter(channel_id="whatsapp", configured=False))

    result = await manager.send_to_preferred("alert")

    assert result == {"error": "no_channel_available"}


@pytest.mark.asyncio
async def test_send_to_channel_unknown_returns_error() -> None:
    manager = ChannelManager(preferred_channel="telegram")

    result = await manager.send_to_channel("unknown", to="x", text="hello")

    assert "error" in result
    assert "Unknown channel" in result["error"]


@pytest.mark.asyncio
async def test_send_to_channel_delegates_send_text() -> None:
    manager = ChannelManager(preferred_channel="telegram")
    adapter = _FakeAdapter(channel_id="telegram")
    manager.register(adapter)

    result = await manager.send_to_channel("telegram", to="123", text="hi", priority="high")

    assert result["status"] == "sent"
    assert adapter.sent[0][0] == "123"
    assert adapter.sent[0][1] == "hi"
    assert adapter.sent[0][2]["priority"] == "high"
