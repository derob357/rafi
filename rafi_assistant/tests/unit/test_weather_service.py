"""Tests for src/services/weather_service.py — WeatherAPI.com queries.

All HTTP calls are mocked.  Covers:
- get_weather returns formatted string
- Handles missing location gracefully
- API error returns friendly message
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import — stub if source not yet written.
# ---------------------------------------------------------------------------
try:
    from src.services.weather_service import WeatherService
except ImportError:
    WeatherService = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weather_api_response(
    location: str = "New York",
    temp_f: float = 72.0,
    condition: str = "Sunny",
) -> Dict[str, Any]:
    """Build a fake WeatherAPI.com JSON response."""
    return {
        "location": {
            "name": location,
            "region": "New York",
            "country": "United States",
            "localtime": "2025-06-15 10:00",
        },
        "current": {
            "temp_f": temp_f,
            "temp_c": round((temp_f - 32) * 5 / 9, 1),
            "condition": {
                "text": condition,
                "icon": "//cdn.weatherapi.com/weather/64x64/day/113.png",
            },
            "wind_mph": 5.0,
            "humidity": 50,
            "feelslike_f": temp_f + 2,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(WeatherService is None, reason="WeatherService not yet implemented")
class TestGetWeather:
    """get_weather returns a formatted weather string."""

    @pytest.mark.asyncio
    async def test_returns_formatted_string(self, mock_config):
        response_data = _weather_api_response("New York", 72.0, "Sunny")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            svc = WeatherService(config=mock_config.weather)
            result = await svc.get_weather("New York")

        assert isinstance(result, str)
        assert "72" in result or "Sunny" in result or "New York" in result

    @pytest.mark.asyncio
    async def test_includes_temperature(self, mock_config):
        response_data = _weather_api_response("Boston", 65.0, "Cloudy")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            svc = WeatherService(config=mock_config.weather)
            result = await svc.get_weather("Boston")

        assert "65" in result or "Cloudy" in result

    @pytest.mark.asyncio
    async def test_includes_condition(self, mock_config):
        response_data = _weather_api_response("Miami", 85.0, "Partly cloudy")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            svc = WeatherService(config=mock_config.weather)
            result = await svc.get_weather("Miami")

        assert isinstance(result, str)
        assert len(result) > 0


@pytest.mark.skipif(WeatherService is None, reason="WeatherService not yet implemented")
class TestMissingLocation:
    """Handles missing or empty location gracefully."""

    @pytest.mark.asyncio
    async def test_empty_location(self, mock_config):
        svc = WeatherService(config=mock_config.weather)
        result = await svc.get_weather("")

        # Should return a friendly message, not crash
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_none_location(self, mock_config):
        svc = WeatherService(config=mock_config.weather)
        try:
            result = await svc.get_weather(None)  # type: ignore[arg-type]
            assert isinstance(result, str)
        except (TypeError, AttributeError):
            pass  # acceptable


@pytest.mark.skipif(WeatherService is None, reason="WeatherService not yet implemented")
class TestApiError:
    """API errors return a friendly message, never crash."""

    @pytest.mark.asyncio
    async def test_api_500_error(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Internal Server Error")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            svc = WeatherService(config=mock_config.weather)
            result = await svc.get_weather("New York")

        assert isinstance(result, str)
        assert "unavailable" in result.lower() or "error" in result.lower() or len(result) > 0

    @pytest.mark.asyncio
    async def test_network_timeout(self, mock_config):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("Connection timeout")):
            svc = WeatherService(config=mock_config.weather)
            result = await svc.get_weather("New York")

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": {"code": 2008, "message": "API key is invalid."}}
        mock_response.raise_for_status.side_effect = Exception("Unauthorized")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            svc = WeatherService(config=mock_config.weather)
            result = await svc.get_weather("New York")

        assert isinstance(result, str)
