"""Authentication and authorization security tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.security
class TestTelegramAuth:
    """Test Telegram user ID authorization."""

    def _make_update(self, user_id: int | None) -> MagicMock:
        """Build a mock Telegram Update with the given user ID."""
        update = MagicMock()
        if user_id is None:
            update.effective_user = None
        else:
            update.effective_user = MagicMock()
            update.effective_user.id = user_id
            update.effective_user.username = "testuser"
            update.effective_user.first_name = "Test"
        update.update_id = 1
        return update

    def _make_config(self, authorized_id: int) -> MagicMock:
        """Build a mock AppConfig with the given authorized user ID."""
        config = MagicMock()
        config.telegram.user_id = authorized_id
        return config

    def test_valid_user_id_passes(self) -> None:
        """Authorized user ID should be allowed."""
        from src.security.auth import verify_telegram_user

        update = self._make_update(123456789)
        config = self._make_config(123456789)
        assert verify_telegram_user(update, config) is True

    def test_invalid_user_id_blocked(self) -> None:
        """Unauthorized user ID should be blocked."""
        from src.security.auth import verify_telegram_user

        update = self._make_update(999999999)
        config = self._make_config(123456789)
        assert verify_telegram_user(update, config) is False

    def test_zero_user_id_blocked(self) -> None:
        from src.security.auth import verify_telegram_user

        update = self._make_update(0)
        config = self._make_config(123456789)
        assert verify_telegram_user(update, config) is False

    def test_negative_user_id_blocked(self) -> None:
        from src.security.auth import verify_telegram_user

        update = self._make_update(-1)
        config = self._make_config(123456789)
        assert verify_telegram_user(update, config) is False

    def test_none_user_id_blocked(self) -> None:
        from src.security.auth import verify_telegram_user

        update = self._make_update(None)
        config = self._make_config(123456789)
        assert verify_telegram_user(update, config) is False


@pytest.mark.security
class TestTwilioSignatureValidation:
    """Test Twilio webhook signature verification."""

    @pytest.mark.asyncio
    async def test_valid_signature_passes(self) -> None:
        """Valid Twilio signature should be accepted."""
        from src.security.auth import verify_twilio_signature

        mock_request = AsyncMock()
        mock_request.url = "https://example.com/api/twilio/voice"
        mock_request.headers = {
            "X-Twilio-Signature": "valid_signature",
        }
        mock_request.form = AsyncMock(return_value={"CallSid": "CA123"})

        with patch("twilio.request_validator.RequestValidator") as MockValidator:
            instance = MockValidator.return_value
            instance.validate.return_value = True
            result = await verify_twilio_signature(mock_request, "test_auth_token")
            assert result is True

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self) -> None:
        """Invalid Twilio signature should be rejected."""
        from src.security.auth import verify_twilio_signature

        mock_request = AsyncMock()
        mock_request.url = "https://example.com/api/twilio/voice"
        mock_request.headers = {
            "X-Twilio-Signature": "forged_signature",
        }
        mock_request.form = AsyncMock(return_value={"CallSid": "CA123"})

        with patch("twilio.request_validator.RequestValidator") as MockValidator:
            instance = MockValidator.return_value
            instance.validate.return_value = False
            result = await verify_twilio_signature(mock_request, "test_auth_token")
            assert result is False

    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self) -> None:
        """Missing Twilio signature header should be rejected."""
        from src.security.auth import verify_twilio_signature

        mock_request = AsyncMock()
        mock_request.url = "https://example.com/api/twilio/voice"
        mock_request.headers = {}  # No signature header
        mock_request.form = AsyncMock(return_value={})

        result = await verify_twilio_signature(mock_request, "test_auth_token")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_auth_token_rejected(self) -> None:
        """Empty auth token should reject all requests."""
        from src.security.auth import verify_twilio_signature

        mock_request = AsyncMock()
        mock_request.url = "https://example.com/api/twilio/voice"
        mock_request.headers = {"X-Twilio-Signature": "some_sig"}
        mock_request.form = AsyncMock(return_value={})

        result = await verify_twilio_signature(mock_request, "")
        assert result is False
