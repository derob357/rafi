import pytest
import sys
from unittest.mock import MagicMock, AsyncMock, patch

# Mock playwright before importing BrowserService
mock_playwright_mod = MagicMock()
sys.modules["playwright"] = mock_playwright_mod
sys.modules["playwright.async_api"] = MagicMock()

from src.services.browser_service import BrowserService

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def browser_service():
    return BrowserService(config=MagicMock())

@pytest.mark.anyio
async def test_browser_browse_success(browser_service):
    # Mock playwright
    mock_page = AsyncMock()
    mock_page.title.return_value = "Example Title"
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.close = AsyncMock()
    
    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page
    
    browser_service.context = mock_context
    
    with patch("tempfile.gettempdir", return_value="/tmp"):
        result = await browser_service.browse("https://example.com", "Read the title")
        
        assert result["status"] == "success"
        assert result["title"] == "Example Title"
        assert "screenshot" in result
        mock_page.goto.assert_called_with("https://example.com", wait_until="networkidle")

@pytest.mark.anyio
async def test_browser_search_success(browser_service):
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.eval_on_selector_all.return_value = [
        {"title": "Result 1", "url": "https://r1.com"},
        {"title": "Result 2", "url": "https://r2.com"}
    ]
    mock_page.close = AsyncMock()
    
    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page
    
    browser_service.context = mock_context
    
    results = await browser_service.search("test query")
    
    assert len(results) == 2
    assert results[0]["title"] == "Result 1"
    mock_page.goto.assert_called_with("https://www.google.com/search?q=test query")
