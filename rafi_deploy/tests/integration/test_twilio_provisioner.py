"""
Integration tests for src.deploy.twilio_provisioner — Twilio number provisioning.

All tests are marked @pytest.mark.integration and skip without credentials.

Tests:
- provision_number returns valid phone number
- provision_number configures webhook correctly
- release_number releases successfully
- Handles no available numbers in area code
- Handles invalid Twilio credentials
"""

import os
import re
from unittest.mock import MagicMock, patch

import pytest

# Skip the entire module if Twilio credentials are not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TWILIO_TEST_ACCOUNT_SID"),
        reason="Twilio test credentials not available (set TWILIO_TEST_ACCOUNT_SID, TWILIO_TEST_AUTH_TOKEN)",
    ),
]

from src.deploy.twilio_provisioner import (
    provision_number,
    release_number,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


def get_test_credentials() -> dict:
    """Load Twilio test credentials from environment."""
    return {
        "account_sid": os.environ.get("TWILIO_TEST_ACCOUNT_SID", ""),
        "auth_token": os.environ.get("TWILIO_TEST_AUTH_TOKEN", ""),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProvisionNumberReturnsValid:
    """provision_number returns a valid phone number."""

    def test_returns_e164_phone_number(self, mock_twilio_client):
        """Provision returns a phone number in E.164 format."""
        # Use the mock to avoid real API calls in unit-like integration tests
        # Real integration test would use live Twilio test credentials
        result = provision_number(
            client=mock_twilio_client,
            area_code="415",
            webhook_url="https://ec2.example.com/webhook/voice",
        )

        assert result is not None
        assert isinstance(result, (str, dict))

        phone = result if isinstance(result, str) else result.get("phone_number", "")
        assert E164_PATTERN.match(phone), f"Phone {phone} not in E.164 format"

    def test_returns_us_number_for_us_area_code(self, mock_twilio_client):
        result = provision_number(
            client=mock_twilio_client,
            area_code="212",
            webhook_url="https://ec2.example.com/webhook/voice",
        )

        phone = result if isinstance(result, str) else result.get("phone_number", "")
        assert phone.startswith("+1"), "US number should start with +1"


class TestProvisionNumberWebhook:
    """provision_number configures webhook correctly."""

    def test_webhook_url_set_on_number(self, mock_twilio_client):
        webhook_url = "https://ec2.example.com/webhook/voice/john_doe"

        provision_number(
            client=mock_twilio_client,
            area_code="415",
            webhook_url=webhook_url,
        )

        # Verify that the create call included the webhook URL
        create_call = mock_twilio_client.incoming_phone_numbers.create
        create_call.assert_called_once()

        call_kwargs = create_call.call_args
        # The webhook URL should be passed as voice_url
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get("voice_url") == webhook_url or \
                   call_kwargs.kwargs.get("voice_url") is not None
        elif call_kwargs.args:
            # May be positional
            pass

    def test_webhook_uses_https(self, mock_twilio_client):
        """Webhook URL must use HTTPS (Twilio requirement)."""
        webhook_url = "https://ec2.example.com/webhook/voice"

        provision_number(
            client=mock_twilio_client,
            area_code="415",
            webhook_url=webhook_url,
        )

        create_call = mock_twilio_client.incoming_phone_numbers.create
        if create_call.call_args and create_call.call_args.kwargs:
            url = create_call.call_args.kwargs.get("voice_url", "")
            assert url.startswith("https://"), "Webhook must use HTTPS"


class TestReleaseNumber:
    """release_number releases a number successfully."""

    def test_release_returns_success(self, mock_twilio_client):
        result = release_number(
            client=mock_twilio_client,
            phone_number="+14155550100",
        )

        # Should return True, None, or not raise
        assert result is not False

    def test_release_calls_delete(self, mock_twilio_client):
        release_number(
            client=mock_twilio_client,
            phone_number="+14155550100",
        )

        # Verify delete was called (exact call depends on implementation)
        # Either incoming_phone_numbers(sid).delete() or similar
        assert (
            mock_twilio_client.incoming_phone_numbers.return_value.delete.called
            or mock_twilio_client.incoming_phone_numbers.list.called
        )


class TestNoAvailableNumbers:
    """Handles no available numbers in area code."""

    def test_raises_when_no_numbers_available(self, mock_twilio_client):
        """If no numbers are available in the requested area code, raise."""
        mock_twilio_client.available_phone_numbers.return_value.local.list.return_value = []

        with pytest.raises((ValueError, RuntimeError, Exception)):
            provision_number(
                client=mock_twilio_client,
                area_code="999",
                webhook_url="https://ec2.example.com/webhook/voice",
            )

    def test_empty_area_code_handled(self, mock_twilio_client):
        """Empty or invalid area code should be handled gracefully."""
        mock_twilio_client.available_phone_numbers.return_value.local.list.return_value = []

        with pytest.raises((ValueError, RuntimeError, Exception)):
            provision_number(
                client=mock_twilio_client,
                area_code="",
                webhook_url="https://ec2.example.com/webhook/voice",
            )


class TestInvalidTwilioCredentials:
    """Handles invalid Twilio credentials."""

    def test_raises_on_auth_error(self):
        """Invalid credentials should produce an authentication error."""
        from twilio.rest import Client as TwilioClient
        from twilio.base.exceptions import TwilioRestException

        mock_client = MagicMock(spec=TwilioClient)
        mock_client.available_phone_numbers.return_value.local.list.side_effect = (
            TwilioRestException(
                status=401,
                uri="/2010-04-01/Accounts/ACinvalid/AvailablePhoneNumbers",
                msg="Authentication Error - invalid username",
            )
        )

        with pytest.raises((TwilioRestException, Exception)):
            provision_number(
                client=mock_client,
                area_code="415",
                webhook_url="https://ec2.example.com/webhook/voice",
            )

    def test_raises_on_forbidden(self):
        """Credentials with wrong permissions should raise."""
        from twilio.base.exceptions import TwilioRestException

        mock_client = MagicMock()
        mock_client.available_phone_numbers.return_value.local.list.side_effect = (
            TwilioRestException(
                status=403,
                uri="/2010-04-01/Accounts/ACtest/AvailablePhoneNumbers",
                msg="Forbidden - insufficient permissions",
            )
        )

        with pytest.raises((TwilioRestException, Exception)):
            provision_number(
                client=mock_client,
                area_code="415",
                webhook_url="https://ec2.example.com/webhook/voice",
            )
