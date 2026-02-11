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
    def __init__(self, registry, *, simulate: bool = False, frame_rate: float = 6.0, camera_index: int = 0):
        self.registry = registry
        self._camera_active = False
        self._screen_active = False
        self._capture_task: Optional[asyncio.Task] = None
        self._simulate = simulate
        self._frame_rate = max(1.0, frame_rate)
        self._camera_index = camera_index
        self._camera = None
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
        logger.info(
            "CaptureDispatcher: Started capture loop (Camera: %s, Screen: %s)",
            self._camera_active,
            self._screen_active,
        )

        try:
            if self._camera_active and not self._simulate:
                self._camera = cv2.VideoCapture(self._camera_index)
                if not self._camera.isOpened():
                    logger.warning("Camera device not available")
                    self._camera.release()
                    self._camera = None

            while self._camera_active or self._screen_active:
                mode = "camera" if self._camera_active else "screen"

                if self._simulate:
                    await self.registry.broadcast_event(
                        "visual_frame",
                        {"mode": mode, "status": "active"},
                    )
                else:
                    frame = None
                    if self._camera_active and self._camera is not None:
                        ok, frame = self._camera.read()
                        if not ok:
                            frame = None
                    elif self._screen_active:
                        monitor = self.sct.monitors[1]
                        img = self.sct.grab(monitor)
                        frame = np.array(img)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                    if frame is not None:
                        await self._broadcast_frame(frame, mode)
                    else:
                        await self.registry.broadcast_event(
                            "visual_frame",
                            {"mode": mode, "status": "no_frame"},
                        )

                await asyncio.sleep(1.0 / self._frame_rate)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in capture loop: %s", e)
        finally:
            if self._camera is not None:
                self._camera.release()
                self._camera = None

    async def _broadcast_frame(self, frame: np.ndarray, mode: str) -> None:
        """Encode a frame and broadcast to the UI."""
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            await self.registry.broadcast_event(
                "visual_frame",
                {"mode": mode, "status": "encode_failed"},
            )
            return

        await self.registry.broadcast_event(
            "visual_frame",
            {"mode": mode, "jpeg": buffer.tobytes(), "status": "active"},
        )
