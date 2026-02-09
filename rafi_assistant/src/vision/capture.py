import cv2
import mss
import numpy as np
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CaptureDispatcher:
    """
    Handles webcam and screen capture for the vision pipeline.
    
    Toggles between modes and pushes frames (or metadata) to the ServiceRegistry.
    """
    def __init__(self, registry):
        self.registry = registry
        self._camera_active = False
        self._screen_active = False
        self._capture_task: Optional[asyncio.Task] = None
        self.sct = mss.mss()

    async def toggle_camera(self, enabled: bool):
        """Enable or disable webcam capture."""
        self._camera_active = enabled
        if enabled:
            self._screen_active = False
            await self._start_capture()
        else:
            if not self._screen_active:
                await self._stop_capture()

    async def toggle_screen(self, enabled: bool):
        """Enable or disable screen capture."""
        self._screen_active = enabled
        if enabled:
            self._camera_active = False
            await self._start_capture()
        else:
            if not self._camera_active:
                await self._stop_capture()

    async def _start_capture(self):
        if self._capture_task:
            return
        self._capture_task = asyncio.create_task(self._capture_loop())

    async def _stop_capture(self):
        if self._capture_task:
            self._capture_task.cancel()
            self._capture_task = None
        logger.info("CaptureDispatcher: Stopped capture")

    async def _capture_loop(self):
        """Main capture loop that grabs frames and notifies the registry."""
        logger.info(f"CaptureDispatcher: Started capture loop (Camera: {self._camera_active}, Screen: {self._screen_active})")
        
        try:
            while self._camera_active or self._screen_active:
                # Placeholder for frame capture logic
                # For a real implementation, we'd use cv2.VideoCapture(0) or self.sct.grab()
                
                # Emit visual metadata to registry
                mode = "camera" if self._camera_active else "screen"
                await self.registry.broadcast_event("visual_input", {"mode": mode, "status": "active"})
                
                # Throttle to 1 FPS for initial implementation
                await asyncio.sleep(1.0) 
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in capture loop: {e}")
