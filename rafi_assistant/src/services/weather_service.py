"""Weather service using WeatherAPI.com.

Provides current weather and forecast data for locations, with
calendar-aware lookups that extract locations from upcoming events.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from src.config.loader import WeatherConfig
from src.security.validators import safe_get

logger = logging.getLogger(__name__)

WEATHER_API_BASE = "https://api.weatherapi.com/v1"
REQUEST_TIMEOUT = 10.0


class WeatherService:
    """WeatherAPI.com client for weather lookups."""

    def __init__(self, config: WeatherConfig) -> None:
        self._api_key = config.api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        logger.info("Weather service initialized")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            logger.debug("Weather service client closed")

    def _get_client(self) -> httpx.AsyncClient:
        """Get the HTTP client, ensuring it is initialized."""
        if self._client is None:
            raise RuntimeError("Weather service not initialized. Call initialize() first.")
        return self._client

    async def get_weather(self, location: str) -> str:
        """Get current weather and forecast for a location.

        Args:
            location: City name or location (e.g., 'New York, NY', '10001').

        Returns:
            Formatted weather string. Returns an error message if the
            lookup fails (never raises).
        """
        if not location or not location.strip():
            return "Weather information unavailable: no location provided."

        client = self._get_client()

        try:
            response = await client.get(
                f"{WEATHER_API_BASE}/forecast.json",
                params={
                    "key": self._api_key,
                    "q": location.strip(),
                    "days": 1,
                    "aqi": "no",
                    "alerts": "no",
                },
            )
            response.raise_for_status()
            data = response.json()

            # Extract current conditions
            current = safe_get(data, "current", {})
            location_data = safe_get(data, "location", {})
            forecast_day = safe_get(
                safe_get(
                    safe_get(safe_get(data, "forecast", {}), "forecastday", [{}]),
                    0,
                    {},
                ),
                "day",
                {},
            )

            # Try to get forecastday safely
            forecast_obj = safe_get(data, "forecast", {})
            forecastdays = forecast_obj.get("forecastday", []) if isinstance(forecast_obj, dict) else []
            if forecastdays and isinstance(forecastdays, list) and len(forecastdays) > 0:
                forecast_day = safe_get(forecastdays[0], "day", {})
            else:
                forecast_day = {}

            city = safe_get(location_data, "name", location)
            region = safe_get(location_data, "region", "")
            condition = safe_get(safe_get(current, "condition", {}), "text", "Unknown")
            temp_f = safe_get(current, "temp_f", "N/A")
            temp_c = safe_get(current, "temp_c", "N/A")
            feels_like_f = safe_get(current, "feelslike_f", "N/A")
            humidity = safe_get(current, "humidity", "N/A")
            wind_mph = safe_get(current, "wind_mph", "N/A")
            wind_dir = safe_get(current, "wind_dir", "")

            high_f = safe_get(forecast_day, "maxtemp_f", "N/A")
            low_f = safe_get(forecast_day, "mintemp_f", "N/A")
            chance_rain = safe_get(forecast_day, "daily_chance_of_rain", "0")

            weather_str = (
                f"Weather for {city}"
                f"{', ' + region if region else ''}:\n"
                f"Currently: {condition}, {temp_f}F ({temp_c}C)\n"
                f"Feels like: {feels_like_f}F\n"
                f"High: {high_f}F / Low: {low_f}F\n"
                f"Humidity: {humidity}%\n"
                f"Wind: {wind_mph} mph {wind_dir}\n"
                f"Chance of rain: {chance_rain}%"
            )

            logger.info("Weather retrieved for %s", city)
            return weather_str

        except httpx.HTTPStatusError as e:
            logger.error("Weather API HTTP error for '%s': %s", location, e.response.status_code)
            return "Weather information is temporarily unavailable."
        except httpx.TimeoutException:
            logger.error("Weather API timeout for '%s'", location)
            return "Weather information is temporarily unavailable."
        except Exception as e:
            logger.error("Weather API error for '%s': %s", location, e)
            return "Weather information is temporarily unavailable."

    async def get_weather_for_event(
        self,
        event: Optional[dict[str, Any]],
    ) -> str:
        """Get weather for a calendar event's location.

        Args:
            event: Calendar event dict with optional 'location' key.

        Returns:
            Weather string, or a message indicating no location is available.
        """
        if event is None:
            return "No upcoming event found to check weather for."

        location = event.get("location", "")
        if not location or not location.strip():
            summary = event.get("summary", "your next event")
            return f"No location set for '{summary}', so weather lookup is not available."

        return await self.get_weather(location)
