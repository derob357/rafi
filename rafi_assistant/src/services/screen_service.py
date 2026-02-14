import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ScreenService:
    """
    Service for local machine automation (keyboard/mouse).
    
    Complementary to BrowserService for interacting with native desktop apps.
    """
    def __init__(self, registry=None):
        self.registry = registry
        try:
            import pyautogui
            # Fail-safe: move mouse to corner to abort
            pyautogui.FAILSAFE = True
        except (ImportError, KeyError, OSError):
            logger.warning("pyautogui unavailable (no display or not installed). Screen control disabled.")

    async def move_mouse(self, x: int, y: int) -> Dict[str, Any]:
        """Move mouse to specific coordinates."""
        try:
            import pyautogui
            await asyncio.to_thread(pyautogui.moveTo, x, y, duration=0.25)
            return {"status": "success", "action": "move_mouse", "coords": (x, y)}
        except Exception as e:
            logger.error(f"Mouse move failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def click(self, x: int = None, y: int = None, button: str = 'left') -> Dict[str, Any]:
        """Click at current position or specified coordinates."""
        try:
            import pyautogui
            await asyncio.to_thread(pyautogui.click, x=x, y=y, button=button)
            return {"status": "success", "action": "click", "coords": (x, y)}
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def type_text(self, text: str, interval: float = 0.1) -> Dict[str, Any]:
        """Type text on the keyboard."""
        try:
            import pyautogui
            await asyncio.to_thread(pyautogui.write, text, interval=interval)
            return {"status": "success", "action": "type_text", "text": text}
        except Exception as e:
            logger.error(f"Typing failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def press_key(self, key: str) -> Dict[str, Any]:
        """Press a specific key (e.g., 'enter', 'esc', 'ctrl')."""
        try:
            import pyautogui
            await asyncio.to_thread(pyautogui.press, key)
            return {"status": "success", "action": "press_key", "key": key}
        except Exception as e:
            logger.error(f"Key press failed: {e}")
            return {"status": "failed", "error": str(e)}
