import os
import sys

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

_no_display = (
    sys.platform != "darwin"
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
)

pytestmark = pytest.mark.skipif(
    _no_display,
    reason="Screen capture requires a display server (not available in headless Docker)",
)

from src.vision.capture import CaptureDispatcher

@pytest.mark.asyncio
async def test_capture_dispatcher_toggle_camera():
    """Test camera toggling in CaptureDispatcher."""
    registry = MagicMock()
    registry.broadcast_event = AsyncMock()
    
    dispatcher = CaptureDispatcher(registry, simulate=True)
    
    await dispatcher.toggle_camera(True)
    assert dispatcher._camera_active is True
    assert dispatcher._capture_task is not None
    
    await dispatcher.toggle_camera(False)
    assert dispatcher._camera_active is False
    # Task should stop if screen is also off
    assert dispatcher._capture_task is None

@pytest.mark.asyncio
async def test_capture_dispatcher_toggle_screen():
    """Test screen toggling in CaptureDispatcher."""
    registry = MagicMock()
    registry.broadcast_event = AsyncMock()
    
    dispatcher = CaptureDispatcher(registry, simulate=True)
    
    await dispatcher.toggle_screen(True)
    assert dispatcher._screen_active is True
    
    await dispatcher.toggle_screen(False)
    assert dispatcher._screen_active is False
    assert dispatcher._capture_task is None
