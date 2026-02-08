"""Integration tests for WeatherAPI.com."""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "Weather API integration tests require live credentials"
HAS_CREDENTIALS = bool(os.environ.get("WEATHER_TEST_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason=SKIP_REASON)
class TestWeatherAPIIntegration:
    """Integration tests against live WeatherAPI.com."""

    @pytest.fixture(autouse=True)
    def setup_service(self) -> None:
        from unittest.mock import AsyncMock
        from src.services.weather_service import WeatherService

        from src.config.loader import WeatherConfig

        config = WeatherConfig(
            api_key=os.environ.get("WEATHER_TEST_API_KEY", "placeholder"),
        )
        self.service = WeatherService(config=config)

    @pytest.mark.asyncio
    async def test_get_weather_valid_location(self) -> None:
        result = await self.service.get_weather("New York")
        assert result is not None
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_weather_invalid_location(self) -> None:
        result = await self.service.get_weather("xyznonexistentplace12345")
        assert result is not None  # Should return error message, not crash

    @pytest.mark.asyncio
    async def test_get_weather_empty_location(self) -> None:
        result = await self.service.get_weather("")
        assert result is not None
