---
name: weather
description: Get current weather and forecasts.
tools:
  - get_weather
requires:
  env:
    - WEATHER_API_KEY
---

# Weather Skill

- `get_weather`: Get weather for a location. If no location given, uses the next calendar event's location.
