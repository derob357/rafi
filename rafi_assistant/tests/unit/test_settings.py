"""Tests for settings get/set via Supabase.

Covers:
- Get / set settings via Supabase
- Default values
- Quiet hours validation (start < end, wrapping midnight)
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import — stub if not yet written.  The settings management may live in
# the scheduler, a dedicated settings module, or the task/note service layer.
# ---------------------------------------------------------------------------
try:
    from src.services.settings_service import SettingsService
except ImportError:
    try:
        from src.scheduling.scheduler import SettingsService
    except ImportError:
        SettingsService = None  # type: ignore[assignment,misc]

# Also try importing the config model for defaults
try:
    from src.config.loader import SettingsConfig
except ImportError:
    SettingsConfig = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_rows(overrides: Dict[str, str] | None = None) -> list:
    """Build fake Supabase settings rows."""
    defaults = {
        "morning_briefing_time": "08:00",
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "reminder_lead_minutes": "15",
        "min_snooze_minutes": "5",
    }
    if overrides:
        defaults.update(overrides)
    return [{"key": k, "value": v, "updated_at": "2025-06-15T10:00:00+00:00"} for k, v in defaults.items()]


# ---------------------------------------------------------------------------
# Tests: Get/Set settings
# ---------------------------------------------------------------------------


@pytest.mark.skipif(SettingsService is None, reason="SettingsService not yet implemented")
class TestGetSetSettings:
    """Get and set settings via Supabase."""

    def test_get_setting(self, mock_supabase, mock_config):
        row = {"key": "morning_briefing_time", "value": "08:00"}
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=row
        )

        svc = SettingsService(mock_config, mock_supabase)
        result = svc.get_setting("morning_briefing_time")

        assert result == "08:00"

    def test_set_setting(self, mock_supabase, mock_config):
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

        svc = SettingsService(mock_config, mock_supabase)
        svc.set_setting("morning_briefing_time", "09:00")

        mock_supabase.table.return_value.upsert.assert_called_once()

    def test_get_all_settings(self, mock_supabase, mock_config):
        rows = _settings_rows()
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=rows)

        svc = SettingsService(mock_config, mock_supabase)
        result = svc.get_all_settings()

        assert isinstance(result, dict)
        assert "morning_briefing_time" in result

    def test_set_quiet_hours(self, mock_supabase, mock_config):
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

        svc = SettingsService(mock_config, mock_supabase)
        svc.set_setting("quiet_hours_start", "23:00")
        svc.set_setting("quiet_hours_end", "06:00")

        assert mock_supabase.table.return_value.upsert.call_count == 2


# ---------------------------------------------------------------------------
# Tests: Default values
# ---------------------------------------------------------------------------


class TestDefaultValues:
    """Settings have correct default values from the config model."""

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_briefing_time(self):
        cfg = SettingsConfig()
        assert cfg.morning_briefing_time == "08:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_quiet_hours_start(self):
        cfg = SettingsConfig()
        assert cfg.quiet_hours_start == "22:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_quiet_hours_end(self):
        cfg = SettingsConfig()
        assert cfg.quiet_hours_end == "07:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_reminder_lead(self):
        cfg = SettingsConfig()
        assert cfg.reminder_lead_minutes == 15

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_snooze(self):
        cfg = SettingsConfig()
        assert cfg.min_snooze_minutes == 5

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_save_to_disk(self):
        cfg = SettingsConfig()
        assert cfg.save_to_disk is False

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_default_timezone(self):
        cfg = SettingsConfig()
        assert cfg.timezone == "America/New_York"


# ---------------------------------------------------------------------------
# Tests: Quiet hours validation
# ---------------------------------------------------------------------------


class TestQuietHoursValidation:
    """Quiet hours accept valid configurations including midnight wrapping."""

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_normal_quiet_hours(self):
        """22:00 to 07:00 — start > end (wraps midnight). Should be valid."""
        cfg = SettingsConfig(quiet_hours_start="22:00", quiet_hours_end="07:00")
        assert cfg.quiet_hours_start == "22:00"
        assert cfg.quiet_hours_end == "07:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_same_day_quiet_hours(self):
        """13:00 to 15:00 — start < end (same day). Should be valid."""
        cfg = SettingsConfig(quiet_hours_start="13:00", quiet_hours_end="15:00")
        assert cfg.quiet_hours_start == "13:00"
        assert cfg.quiet_hours_end == "15:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_midnight_start(self):
        cfg = SettingsConfig(quiet_hours_start="00:00", quiet_hours_end="06:00")
        assert cfg.quiet_hours_start == "00:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_midnight_end(self):
        cfg = SettingsConfig(quiet_hours_start="20:00", quiet_hours_end="00:00")
        assert cfg.quiet_hours_end == "00:00"

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_invalid_start_time_format(self):
        with pytest.raises(ValueError):
            SettingsConfig(quiet_hours_start="10pm")

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_invalid_end_time_format(self):
        with pytest.raises(ValueError):
            SettingsConfig(quiet_hours_end="7am")

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_invalid_hour_value(self):
        with pytest.raises(ValueError):
            SettingsConfig(quiet_hours_start="25:00")

    @pytest.mark.skipif(SettingsConfig is None, reason="SettingsConfig not yet implemented")
    def test_invalid_minute_value(self):
        with pytest.raises(ValueError):
            SettingsConfig(quiet_hours_end="07:60")
