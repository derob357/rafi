import pytest
import sys
from unittest.mock import MagicMock, patch

# Mock pyautogui before importing ScreenService
sys.modules["pyautogui"] = MagicMock()

from src.services.screen_service import ScreenService

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def screen_service():
    return ScreenService()

@pytest.mark.anyio
async def test_mouse_move(screen_service):
    with patch("pyautogui.moveTo") as mock_move:
        result = await screen_service.move_mouse(100, 200)
        assert result["status"] == "success"
        mock_move.assert_called_once()

@pytest.mark.anyio
async def test_mouse_click(screen_service):
    with patch("pyautogui.click") as mock_click:
        result = await screen_service.click(100, 200)
        assert result["status"] == "success"
        mock_click.assert_called_once()

@pytest.mark.anyio
async def test_keyboard_type(screen_service):
    with patch("pyautogui.write") as mock_write:
        result = await screen_service.type_text("hello")
        assert result["status"] == "success"
        mock_write.assert_called_once_with("hello", interval=0.1)
