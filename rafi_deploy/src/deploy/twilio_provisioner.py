"""Provision and manage Twilio phone numbers via the Twilio REST API.

Handles searching for available numbers, purchasing them, configuring
voice webhook URLs, and releasing numbers when clients are removed.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)

# Default country for number search
DEFAULT_COUNTRY = "US"

# Twilio webhook path on the EC2 instance (per-client routing)
WEBHOOK_PATH_TEMPLATE = "/twilio/voice/{client_name}"


class TwilioProvisioningError(Exception):
    """Raised when Twilio number provisioning fails."""

    pass


def _get_twilio_client() -> TwilioClient:
    """Create a Twilio REST client from environment variables.

    Returns:
        Configured TwilioClient instance.

    Raises:
        TwilioProvisioningError: If credentials are not set.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

    if not account_sid:
        raise TwilioProvisioningError(
            "TWILIO_ACCOUNT_SID environment variable is not set"
        )
    if not auth_token:
        raise TwilioProvisioningError(
            "TWILIO_AUTH_TOKEN environment variable is not set"
        )

    return TwilioClient(account_sid, auth_token)


def _get_ec2_base_url() -> str:
    """Get the EC2 base URL for webhook configuration.

    Returns:
        The base URL string (e.g., 'https://rafi.example.com').

    Raises:
        TwilioProvisioningError: If the URL is not configured.
    """
    base_url = os.environ.get("EC2_BASE_URL")
    if not base_url:
        raise TwilioProvisioningError(
            "EC2_BASE_URL environment variable is not set. "
            "This should be the HTTPS URL of the EC2 instance "
            "(e.g., https://rafi.example.com)."
        )
    return base_url.rstrip("/")


def search_available_numbers(
    area_code: str | None = None,
    country: str = DEFAULT_COUNTRY,
    limit: int = 5,
) -> list[dict[str, str]]:
    """Search for available Twilio phone numbers.

    Args:
        area_code: Optional area code to filter by (e.g., '212').
        country: ISO country code. Defaults to 'US'.
        limit: Maximum number of results. Defaults to 5.

    Returns:
        List of dicts with 'phone_number' and 'friendly_name' keys.

    Raises:
        TwilioProvisioningError: If the search fails.
    """
    client = _get_twilio_client()

    try:
        search_kwargs: dict[str, object] = {
            "voice_enabled": True,
            "sms_enabled": True,
            "limit": limit,
        }
        if area_code:
            search_kwargs["area_code"] = area_code

        available = client.available_phone_numbers(country).local.list(
            **search_kwargs
        )

        if not available:
            logger.warning(
                "No available numbers found (area_code=%s, country=%s)",
                area_code,
                country,
            )
            return []

        results = []
        for number in available:
            results.append(
                {
                    "phone_number": number.phone_number,
                    "friendly_name": number.friendly_name,
                }
            )
            logger.debug("Found available number: %s", number.phone_number)

        logger.info("Found %d available numbers", len(results))
        return results

    except TwilioRestException as exc:
        raise TwilioProvisioningError(
            f"Failed to search available numbers: {exc}"
        ) from exc


def provision_number(
    client_name: str,
    area_code: str | None = None,
    country: str = DEFAULT_COUNTRY,
    phone_number: str | None = None,
) -> str:
    """Provision a new Twilio phone number for a client.

    Searches for available numbers (unless a specific number is provided),
    purchases the first one, and configures its voice webhook URL to point
    to the client's endpoint on the EC2 instance.

    Args:
        client_name: Sanitized client name for webhook URL routing.
        area_code: Optional preferred area code.
        country: ISO country code. Defaults to 'US'.
        phone_number: If provided, purchases this specific number instead
            of searching.

    Returns:
        The provisioned phone number in E.164 format (e.g., '+12125551234').

    Raises:
        TwilioProvisioningError: If no numbers are available or the
            purchase fails.
    """
    twilio_client = _get_twilio_client()
    base_url = _get_ec2_base_url()

    webhook_url = f"{base_url}{WEBHOOK_PATH_TEMPLATE.format(client_name=client_name)}"
    logger.info("Webhook URL for client '%s': %s", client_name, webhook_url)

    # Determine which number to buy
    if phone_number:
        target_number = phone_number
        logger.info("Using specified phone number: %s", target_number)
    else:
        available = search_available_numbers(
            area_code=area_code, country=country, limit=1
        )
        if not available:
            raise TwilioProvisioningError(
                f"No phone numbers available "
                f"(area_code={area_code}, country={country}). "
                f"Try a different area code or country."
            )
        target_number = available[0]["phone_number"]
        logger.info("Selected number to provision: %s", target_number)

    # Purchase the number
    try:
        incoming_number = twilio_client.incoming_phone_numbers.create(
            phone_number=target_number,
            voice_url=webhook_url,
            voice_method="POST",
            friendly_name=f"Rafi - {client_name}",
        )

        logger.info(
            "Provisioned number %s (SID: %s) for client '%s'",
            incoming_number.phone_number,
            incoming_number.sid,
            client_name,
        )
        print(f"Provisioned Twilio number: {incoming_number.phone_number}")
        return incoming_number.phone_number

    except TwilioRestException as exc:
        raise TwilioProvisioningError(
            f"Failed to purchase number {target_number}: {exc}"
        ) from exc


def update_webhook(phone_number: str, client_name: str) -> None:
    """Update the voice webhook URL for an existing Twilio number.

    Args:
        phone_number: The phone number to update (E.164 format).
        client_name: The client name for routing.

    Raises:
        TwilioProvisioningError: If the number is not found or the
            update fails.
    """
    twilio_client = _get_twilio_client()
    base_url = _get_ec2_base_url()

    webhook_url = f"{base_url}{WEBHOOK_PATH_TEMPLATE.format(client_name=client_name)}"

    try:
        # Find the number SID
        numbers = twilio_client.incoming_phone_numbers.list(
            phone_number=phone_number
        )
        if not numbers:
            raise TwilioProvisioningError(
                f"Phone number {phone_number} not found in Twilio account"
            )

        number_resource = numbers[0]
        number_resource.update(
            voice_url=webhook_url,
            voice_method="POST",
        )

        logger.info(
            "Updated webhook for %s to %s", phone_number, webhook_url
        )

    except TwilioRestException as exc:
        raise TwilioProvisioningError(
            f"Failed to update webhook for {phone_number}: {exc}"
        ) from exc


def release_number(phone_number: str) -> None:
    """Release a Twilio phone number.

    This removes the number from the Twilio account, which stops all
    billing for it. This action cannot be undone -- the number may
    be reassigned to another Twilio customer.

    Args:
        phone_number: The phone number to release (E.164 format).

    Raises:
        TwilioProvisioningError: If the number cannot be found or
            the release fails.
    """
    twilio_client = _get_twilio_client()

    try:
        numbers = twilio_client.incoming_phone_numbers.list(
            phone_number=phone_number
        )
        if not numbers:
            raise TwilioProvisioningError(
                f"Phone number {phone_number} not found in Twilio account"
            )

        number_sid = numbers[0].sid
        twilio_client.incoming_phone_numbers(number_sid).delete()

        logger.info("Released Twilio number: %s (SID: %s)", phone_number, number_sid)
        print(f"Released Twilio number: {phone_number}")

    except TwilioRestException as exc:
        raise TwilioProvisioningError(
            f"Failed to release number {phone_number}: {exc}"
        ) from exc


def get_number_info(phone_number: str) -> dict[str, str] | None:
    """Get information about a Twilio phone number.

    Args:
        phone_number: The phone number to look up (E.164 format).

    Returns:
        Dict with number details, or None if not found.

    Raises:
        TwilioProvisioningError: If the lookup fails.
    """
    twilio_client = _get_twilio_client()

    try:
        numbers = twilio_client.incoming_phone_numbers.list(
            phone_number=phone_number
        )
        if not numbers:
            return None

        number = numbers[0]
        return {
            "sid": number.sid,
            "phone_number": number.phone_number,
            "friendly_name": number.friendly_name,
            "voice_url": number.voice_url or "",
            "date_created": str(number.date_created) if number.date_created else "",
        }

    except TwilioRestException as exc:
        raise TwilioProvisioningError(
            f"Failed to look up number {phone_number}: {exc}"
        ) from exc
