"""Authentication and authorization helpers.

Provides functions to verify Telegram user identity and
validate Twilio webhook request signatures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastapi import Request
    from telegram import Update

    from src.config.loader import AppConfig

logger = logging.getLogger(__name__)


def verify_telegram_user(update: Update, config: AppConfig) -> bool:
    """Verify that a Telegram update comes from the authorized user.

    Compares the sender's user ID against the configured authorized user ID.
    Unauthorized attempts are logged with available identifying information.

    Args:
        update: The incoming Telegram update object.
        config: Application configuration containing the authorized user_id.

    Returns:
        True if the user is authorized, False otherwise.
    """
    if update.effective_user is None:
        logger.warning(
            "Telegram update received with no effective_user. Update ID: %s",
            update.update_id,
        )
        return False

    sender_id = update.effective_user.id
    authorized_id = config.telegram.user_id

    if sender_id != authorized_id:
        logger.warning(
            "Unauthorized Telegram access attempt. Sender ID: %d, "
            "Username: %s, First name: %s. Expected ID: %d",
            sender_id,
            update.effective_user.username or "N/A",
            update.effective_user.first_name or "N/A",
            authorized_id,
        )
        return False

    return True


async def verify_twilio_signature(
    request: Request,
    auth_token: str,
    base_url: Optional[str] = None,
) -> bool:
    """Validate a Twilio webhook request signature.

    Uses the Twilio request validator to ensure the request actually
    originated from Twilio and was not forged.

    Args:
        request: The incoming FastAPI request object.
        auth_token: The Twilio auth token used for signature validation.
        base_url: Optional base URL override. If None, constructed from request.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        from twilio.request_validator import RequestValidator
    except ImportError:
        logger.error("twilio package not installed; cannot validate webhook signature")
        return False

    validator = RequestValidator(auth_token)

    # Get the signature header
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.warning("Twilio webhook request missing X-Twilio-Signature header")
        return False

    # Build the full URL
    if base_url is not None:
        url = base_url + request.url.path
    else:
        url = str(request.url)

    # Get form data from the request body
    try:
        form_data = await request.form()
        params = {key: form_data[key] for key in form_data}
    except Exception:
        logger.warning("Failed to parse form data from Twilio webhook request")
        params = {}

    # Validate
    is_valid = validator.validate(url, params, signature)

    if not is_valid:
        logger.warning(
            "Invalid Twilio webhook signature. URL: %s, Signature: %s...",
            url,
            signature[:10] if signature else "NONE",
        )

    return is_valid
