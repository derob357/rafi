import logging
import asyncio
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class BrowserService:
    """
    Service for autonomous web browsing using Playwright.
    
    Allows the assistant to navigate websites, search, and extract information.
    """
    def __init__(self, config=None):
        self.config = config
        self.browser = None
        self.context = None
        self._playwright = None

    async def initialize(self):
        """Start the playwright instance."""
        if not self._playwright:
            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context()
            logger.info("BrowserService initialized")

    async def shutdown(self):
        """Close browser and playwright."""
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("BrowserService shutdown")

    async def browse(self, url: str, action_prompt: str = "") -> Dict[str, Any]:
        """
        Navigate to a URL and perform a task.
        
        Note: In a full implementation, this would involve an LLM-in-the-loop 
        to decide on clicks/scrolls. For now, it's a basic navigation + screenshot helper.
        """
        if not self.context:
            await self.initialize()

        page = await self.context.new_page()
        try:
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle")
            
            # Simple metadata extraction
            title = await page.title()
            
            # Take a screenshot for the 'vision' part of the ADA parity
            import tempfile
            import os
            screenshot_path = os.path.join(tempfile.gettempdir(), f"browsing_{int(asyncio.get_event_loop().time())}.png")
            await page.screenshot(path=screenshot_path)
            
            return {
                "url": url,
                "title": title,
                "screenshot": screenshot_path,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Browsing failed: {e}")
            return {"error": str(e), "status": "failed"}
        finally:
            await page.close()

    async def search(self, query: str) -> List[Dict[str, str]]:
        """Perform a Google search (or similar) and return results."""
        if not self.context:
            await self.initialize()
            
        page = await self.context.new_page()
        try:
            await page.goto(f"https://www.google.com/search?q={query}")
            # Extract top 3 results
            results = await page.eval_on_selector_all(
                "div.g",
                "nodes => nodes.slice(0, 3).map(n => ({title: n.querySelector('h3')?.innerText, url: n.querySelector('a')?.href}))"
            )
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
        finally:
            await page.close()
