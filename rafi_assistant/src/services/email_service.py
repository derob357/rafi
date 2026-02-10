"""Gmail service for email management.

Provides functions to list, search, and send emails via the Gmail API,
with HTML stripping and input sanitization before passing content to the LLM.
"""

from __future__ import annotations

import base64
import logging
import os
from email.mime.text import MIMEText
from typing import Any, Optional

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config.loader import AppConfig
from src.db.supabase_client import SupabaseClient
from src.security.sanitizer import sanitize_email_body
from src.security.validators import safe_get
from src.utils.async_utils import await_if_needed

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class EmailService:
    """Gmail API wrapper for reading, searching, and sending emails."""

    def __init__(self, config: AppConfig, db: SupabaseClient) -> None:
        self._config = config
        self._db = db
        self._service: Any = None
        self._credentials: Optional[Credentials] = None
        self._fernet: Optional[Fernet] = None

        encryption_key = os.environ.get("OAUTH_ENCRYPTION_KEY")
        if encryption_key:
            self._fernet = Fernet(encryption_key.encode())

    async def _get_credentials(self) -> Credentials:
        """Load, decrypt, and refresh Google OAuth credentials."""
        if self._credentials and self._credentials.valid:
            return self._credentials

        tokens = await await_if_needed(
            self._db.select(
                "oauth_tokens",
                filters={"provider": "google"},
                limit=1,
            )
        )

        access_token = ""
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

        if tokens:
            token_row = tokens[0]
            access_token = token_row.get("access_token", "")
            refresh_token = token_row.get("refresh_token", "") or refresh_token

            if self._fernet:
                try:
                    access_token = self._fernet.decrypt(access_token.encode()).decode()
                    refresh_token = self._fernet.decrypt(refresh_token.encode()).decode()
                except Exception as e:
                    logger.error("Failed to decrypt OAuth tokens: %s", e)
                    raise RuntimeError("OAuth token decryption failed") from e

        if not refresh_token:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": self._config.google.client_id,
                        "client_secret": self._config.google.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                SCOPES,
            )
            auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
            logger.warning("\n" + "!"*80 + f"\nGMAIL ACTION REQUIRED:\nVisit this URL to authorize Gmail access for Rafi:\n{auth_url}\n" + "!"*80 + "\n")
            raise RuntimeError("Google OAuth tokens not found for Gmail. Set GOOGLE_REFRESH_TOKEN in .env or visit the URL above.")

        self._credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._config.google.client_id,
            client_secret=self._config.google.client_secret,
            scopes=SCOPES,
        )

        if self._credentials.expired and self._credentials.refresh_token:
            try:
                self._credentials.refresh(GoogleAuthRequest())
                logger.info("Gmail OAuth token refreshed")

                new_access = self._credentials.token or ""
                new_refresh = self._credentials.refresh_token or refresh_token

                if self._fernet:
                    new_access = self._fernet.encrypt(new_access.encode()).decode()
                    new_refresh = self._fernet.encrypt(new_refresh.encode()).decode()

                await await_if_needed(
                    self._db.upsert(
                        "oauth_tokens",
                        {
                            "provider": "google",
                            "access_token": new_access,
                            "refresh_token": new_refresh,
                            "expires_at": (
                                self._credentials.expiry.isoformat()
                                if self._credentials.expiry
                                else None
                            ),
                            "scopes": " ".join(SCOPES),
                        },
                        on_conflict="provider",
                    )
                )
            except Exception as e:
                logger.error("Gmail OAuth token refresh failed: %s", e)
                raise

        return self._credentials

    async def initialize(self) -> None:
        """Initialize the Gmail API service."""
        try:
            credentials = await self._get_credentials()
            self._service = build("gmail", "v1", credentials=credentials)
            logger.info("Gmail service initialized")
        except Exception as e:
            logger.error("Failed to initialize Gmail service: %s", e)
            raise

    def _get_service(self) -> Any:
        """Get the Gmail API service, ensuring it is initialized."""
        if self._service is None:
            raise RuntimeError("Gmail service not initialized. Call initialize() first.")
        return self._service

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract and sanitize the email body from a Gmail message payload.

        Handles both simple and multipart message formats.
        """
        body = ""

        # Check for simple body
        data = safe_get(safe_get(payload, "body", {}), "data", "")
        if data:
            try:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                body = ""

        # Check multipart
        parts = payload.get("parts", [])
        if not body and parts:
            for part in parts:
                mime_type = part.get("mimeType", "")
                part_data = safe_get(safe_get(part, "body", {}), "data", "")

                if mime_type == "text/plain" and part_data:
                    try:
                        body = base64.urlsafe_b64decode(part_data).decode(
                            "utf-8", errors="replace"
                        )
                        break
                    except Exception:
                        continue

                if mime_type == "text/html" and part_data and not body:
                    try:
                        html_body = base64.urlsafe_b64decode(part_data).decode(
                            "utf-8", errors="replace"
                        )
                        body = sanitize_email_body(html_body)
                    except Exception:
                        continue

                # Handle nested multipart
                nested_parts = part.get("parts", [])
                for nested in nested_parts:
                    nested_mime = nested.get("mimeType", "")
                    nested_data = safe_get(safe_get(nested, "body", {}), "data", "")
                    if nested_mime == "text/plain" and nested_data:
                        try:
                            body = base64.urlsafe_b64decode(nested_data).decode(
                                "utf-8", errors="replace"
                            )
                            break
                        except Exception:
                            continue

        return sanitize_email_body(body) if body else ""

    def _extract_headers(
        self, headers: list[dict[str, str]]
    ) -> dict[str, str]:
        """Extract common headers (From, To, Subject, Date) from a message."""
        result: dict[str, str] = {}
        for header in headers:
            name = header.get("name", "").lower()
            value = header.get("value", "")
            if name in ("from", "to", "subject", "date"):
                result[name] = value
        return result

    async def list_emails(
        self,
        count: int = 20,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List recent emails from the inbox.

        Args:
            count: Number of emails to retrieve (max 50).
            unread_only: If True, only return unread emails.

        Returns:
            List of email dicts with id, from, to, subject, date, snippet, body.
        """
        count = min(max(count, 1), 50)
        service = self._get_service()

        try:
            query = "is:unread" if unread_only else ""
            result = (
                service.users()
                .messages()
                .list(userId="me", maxResults=count, q=query)
                .execute()
            )

            messages = result.get("messages", [])
            emails = []

            for msg_ref in messages:
                msg_id = msg_ref.get("id", "")
                if not msg_id:
                    continue

                try:
                    msg = (
                        service.users()
                        .messages()
                        .get(userId="me", id=msg_id, format="full")
                        .execute()
                    )

                    payload = msg.get("payload", {})
                    headers = self._extract_headers(payload.get("headers", []))
                    body = self._extract_body(payload)

                    emails.append({
                        "id": msg_id,
                        "from": headers.get("from", ""),
                        "to": headers.get("to", ""),
                        "subject": headers.get("subject", "(No subject)"),
                        "date": headers.get("date", ""),
                        "snippet": msg.get("snippet", ""),
                        "body": body,
                        "labels": msg.get("labelIds", []),
                    })
                except Exception as e:
                    logger.warning("Failed to fetch email %s: %s", msg_id, e)
                    continue

            logger.info("Retrieved %d emails (unread_only=%s)", len(emails), unread_only)
            return emails

        except Exception as e:
            logger.error("Failed to list emails: %s", e)
            return []

    async def search_emails(self, query: str) -> list[dict[str, Any]]:
        """Search emails using Gmail search query syntax.

        Args:
            query: Gmail search query (e.g., 'from:john subject:meeting').

        Returns:
            List of matching email dicts.
        """
        service = self._get_service()

        try:
            result = (
                service.users()
                .messages()
                .list(userId="me", maxResults=20, q=query)
                .execute()
            )

            messages = result.get("messages", [])
            emails = []

            for msg_ref in messages:
                msg_id = msg_ref.get("id", "")
                if not msg_id:
                    continue

                try:
                    msg = (
                        service.users()
                        .messages()
                        .get(userId="me", id=msg_id, format="full")
                        .execute()
                    )

                    payload = msg.get("payload", {})
                    headers = self._extract_headers(payload.get("headers", []))
                    body = self._extract_body(payload)

                    emails.append({
                        "id": msg_id,
                        "from": headers.get("from", ""),
                        "to": headers.get("to", ""),
                        "subject": headers.get("subject", "(No subject)"),
                        "date": headers.get("date", ""),
                        "snippet": msg.get("snippet", ""),
                        "body": body,
                    })
                except Exception as e:
                    logger.warning("Failed to fetch email %s: %s", msg_id, e)
                    continue

            logger.info("Search '%s' returned %d results", query[:50], len(emails))
            return emails

        except Exception as e:
            logger.error("Failed to search emails with query '%s': %s", query[:50], e)
            return []

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> Optional[dict[str, Any]]:
        """Send an email via Gmail.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text email body.

        Returns:
            Sent message dict with id and threadId, or None on failure.
        """
        service = self._get_service()

        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )

            logger.info(
                "Email sent to %s, subject: %s, message ID: %s",
                to,
                subject[:50],
                result.get("id", "N/A"),
            )

            return {
                "id": result.get("id", ""),
                "threadId": result.get("threadId", ""),
            }

        except Exception as e:
            logger.error("Failed to send email to %s: %s", to, e)
            return None

    async def get_email(self, email_id: str) -> Optional[dict[str, Any]]:
        """Get a specific email by its ID.

        Args:
            email_id: Gmail message ID.

        Returns:
            Email dict with full details, or None on failure.
        """
        service = self._get_service()

        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=email_id, format="full")
                .execute()
            )

            payload = msg.get("payload", {})
            headers = self._extract_headers(payload.get("headers", []))
            body = self._extract_body(payload)

            return {
                "id": email_id,
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", "(No subject)"),
                "date": headers.get("date", ""),
                "snippet": msg.get("snippet", ""),
                "body": body,
                "labels": msg.get("labelIds", []),
            }

        except Exception as e:
            logger.error("Failed to get email %s: %s", email_id, e)
            return None

    async def get_unread_count(self) -> int:
        """Get the count of unread emails in the inbox.

        Returns:
            Number of unread emails, or 0 on failure.
        """
        service = self._get_service()

        try:
            result = (
                service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=1)
                .execute()
            )
            return result.get("resultSizeEstimate", 0)
        except Exception as e:
            logger.error("Failed to get unread email count: %s", e)
            return 0
