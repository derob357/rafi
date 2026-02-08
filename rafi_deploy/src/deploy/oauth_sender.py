"""Generate Google OAuth URLs and send authorization links to clients.

Builds the Google OAuth2 authorization URL with the required scopes
for Calendar and Gmail access, then sends it to the client via email
with instructions on how to complete the authorization flow.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

# Google OAuth2 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# Default scopes needed by rafi_assistant
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# SMTP defaults
DEFAULT_SMTP_PORT = 587


class OAuthSenderError(Exception):
    """Raised when OAuth URL generation or email sending fails."""

    pass


def generate_oauth_url(
    client_id: str,
    redirect_uri: str,
    scopes: list[str] | None = None,
    state: str | None = None,
    login_hint: str | None = None,
) -> str:
    """Generate a Google OAuth2 authorization URL.

    Builds the URL that the client will visit to grant Calendar and
    Gmail access to their Rafi assistant.

    Args:
        client_id: Google OAuth client ID.
        redirect_uri: URI where Google will redirect after authorization.
            Must be registered in the Google Cloud Console.
        scopes: List of OAuth scopes to request. Defaults to the standard
            set needed by rafi_assistant.
        state: Optional opaque state parameter for CSRF protection.
        login_hint: Optional email address to pre-fill in the login form.

    Returns:
        The complete authorization URL string.

    Raises:
        OAuthSenderError: If required parameters are missing or invalid.
    """
    if not client_id:
        raise OAuthSenderError("Google OAuth client_id is required")

    if not redirect_uri:
        raise OAuthSenderError("redirect_uri is required")

    if scopes is None:
        scopes = DEFAULT_SCOPES

    if not scopes:
        raise OAuthSenderError("At least one OAuth scope is required")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    }

    if state:
        params["state"] = state

    if login_hint:
        params["login_hint"] = login_hint

    url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    logger.info("Generated OAuth URL for client_id ending in ...%s", client_id[-8:])
    return url


def _get_smtp_config() -> dict[str, str | int]:
    """Get SMTP configuration from environment variables.

    Returns:
        Dict with 'host', 'port', 'username', 'password', and 'from_email'.

    Raises:
        OAuthSenderError: If required variables are not set.
    """
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise OAuthSenderError(
            "SMTP_HOST environment variable is not set. "
            "For Gmail: smtp.gmail.com"
        )

    port = int(os.environ.get("SMTP_PORT", str(DEFAULT_SMTP_PORT)))

    username = os.environ.get("SMTP_USERNAME")
    if not username:
        raise OAuthSenderError("SMTP_USERNAME environment variable is not set")

    password = os.environ.get("SMTP_PASSWORD")
    if not password:
        raise OAuthSenderError(
            "SMTP_PASSWORD environment variable is not set. "
            "For Gmail, use an App Password."
        )

    from_email = os.environ.get("SMTP_FROM_EMAIL", username)

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
    }


def _build_email_body(
    client_name: str,
    oauth_url: str,
    assistant_name: str = "Rafi",
) -> tuple[str, str]:
    """Build the plain-text and HTML email body.

    Args:
        client_name: The client's display name.
        oauth_url: The OAuth authorization URL.
        assistant_name: The name of the assistant.

    Returns:
        Tuple of (plain_text_body, html_body).
    """
    plain_text = f"""\
Hello {client_name},

Your personal AI assistant "{assistant_name}" is almost ready!

To complete the setup, please authorize access to your Google Calendar and Gmail by clicking the link below:

{oauth_url}

What this does:
- Allows your assistant to read and manage your Google Calendar events
- Allows your assistant to read, search, and send emails on your behalf
- You can revoke this access at any time from your Google Account settings

This link is one-time use and will expire. Please click it within 24 hours.

If you have any questions or concerns, please reply to this email.

Best regards,
The Rafi Team
"""

    html_body = f"""\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #2563eb; color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center; }}
        .content {{ background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0; border-radius: 0 0 8px 8px; }}
        .btn {{ display: inline-block; background: #2563eb; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; margin: 16px 0; }}
        .btn:hover {{ background: #1d4ed8; }}
        .info {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 16px; margin: 16px 0; }}
        .footer {{ text-align: center; color: #94a3b8; font-size: 0.875rem; margin-top: 24px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Welcome to {assistant_name}</h1>
    </div>
    <div class="content">
        <p>Hello {client_name},</p>
        <p>Your personal AI assistant <strong>"{assistant_name}"</strong> is almost ready!</p>
        <p>To complete the setup, please authorize access to your Google Calendar and Gmail:</p>
        <p style="text-align: center;">
            <a href="{oauth_url}" class="btn">Authorize Google Access</a>
        </p>
        <div class="info">
            <strong>What this does:</strong>
            <ul>
                <li>Allows your assistant to read and manage your Google Calendar events</li>
                <li>Allows your assistant to read, search, and send emails on your behalf</li>
                <li>You can revoke this access at any time from your Google Account settings</li>
            </ul>
        </div>
        <p><em>This link is one-time use and will expire within 24 hours.</em></p>
        <p>If you have any questions, simply reply to this email.</p>
        <p>Best regards,<br>The Rafi Team</p>
    </div>
    <div class="footer">
        <p>This email was sent by the Rafi AI Assistant platform.</p>
    </div>
</body>
</html>
"""

    return plain_text, html_body


def send_oauth_email(
    client_email: str,
    oauth_url: str,
    client_name: str = "there",
    assistant_name: str = "Rafi",
) -> None:
    """Send the OAuth authorization link to a client via email.

    Sends a well-formatted email with both plain-text and HTML versions
    containing the authorization link and instructions.

    Args:
        client_email: The client's email address.
        oauth_url: The OAuth authorization URL.
        client_name: The client's display name for the greeting.
        assistant_name: The name of the assistant.

    Raises:
        OAuthSenderError: If the email cannot be sent.
    """
    if not client_email:
        raise OAuthSenderError("Client email address is required")

    if not oauth_url:
        raise OAuthSenderError("OAuth URL is required")

    smtp_config = _get_smtp_config()

    # Build the email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Authorize Google Access for Your {assistant_name} Assistant"
    msg["From"] = str(smtp_config["from_email"])
    msg["To"] = client_email

    plain_text, html_body = _build_email_body(
        client_name, oauth_url, assistant_name
    )

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    # Send the email
    try:
        context = ssl.create_default_context()

        with smtplib.SMTP(
            str(smtp_config["host"]), int(smtp_config["port"])
        ) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(
                str(smtp_config["username"]),
                str(smtp_config["password"]),
            )
            server.send_message(msg)

        logger.info("OAuth email sent to %s", client_email)
        print(f"OAuth authorization email sent to: {client_email}")

    except smtplib.SMTPAuthenticationError as exc:
        raise OAuthSenderError(
            f"SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD. "
            f"For Gmail, use an App Password. Error: {exc}"
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise OAuthSenderError(
            f"Recipient address rejected: {client_email}. Error: {exc}"
        ) from exc
    except smtplib.SMTPException as exc:
        raise OAuthSenderError(
            f"Failed to send email: {exc}"
        ) from exc
    except OSError as exc:
        raise OAuthSenderError(
            f"Network error sending email: {exc}"
        ) from exc


def send_oauth_flow(
    client_name: str,
    client_email: str,
    google_client_id: str,
    redirect_uri: str,
    assistant_name: str = "Rafi",
) -> str:
    """Complete OAuth flow: generate URL and send to client.

    Convenience function that generates the OAuth URL and sends it
    to the client in a single call.

    Args:
        client_name: The client's display name.
        client_email: The client's email address.
        google_client_id: Google OAuth client ID.
        redirect_uri: OAuth redirect URI.
        assistant_name: The name of the assistant.

    Returns:
        The generated OAuth URL.

    Raises:
        OAuthSenderError: If URL generation or email sending fails.
    """
    oauth_url = generate_oauth_url(
        client_id=google_client_id,
        redirect_uri=redirect_uri,
        login_hint=client_email,
        state=client_name.replace(" ", "_").lower(),
    )

    send_oauth_email(
        client_email=client_email,
        oauth_url=oauth_url,
        client_name=client_name,
        assistant_name=assistant_name,
    )

    return oauth_url
