"""Google Calendar service for event management.

Provides CRUD operations on Google Calendar events, with automatic
OAuth token refresh, event caching to Supabase, and location extraction
for weather lookups.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config.loader import AppConfig
from src.db.supabase_client import SupabaseClient
from src.security.validators import safe_get
from src.utils.async_utils import await_if_needed

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class CalendarService:
    """Google Calendar API wrapper with caching and token management."""

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
        """Load and refresh Google OAuth credentials.

        Loads tokens from Supabase, decrypts them, and refreshes if expired.
        Updated tokens are re-encrypted and stored back.
        """
        if self._credentials and self._credentials.valid:
            return self._credentials

        # Load tokens from Supabase
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

            # Decrypt tokens if encryption is configured
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
            print("\n" + "!"*80)
            print("GOOGLE CALENDAR ACTION REQUIRED:")
            print(f"Visit this URL to authorize Rafi:\n\n{auth_url}\n")
            print("After authorizing, paste the 'refresh_token' into your .env as GOOGLE_REFRESH_TOKEN.")
            print("!"*80 + "\n")
            
            logger.warning("Google Authorization URL generated: %s", auth_url)
            raise RuntimeError(
                "Google OAuth tokens not found. Set GOOGLE_REFRESH_TOKEN in .env or visit the URL above."
            )

        self._credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._config.google.client_id,
            client_secret=self._config.google.client_secret,
            scopes=SCOPES,
        )

        # Refresh if expired
        if self._credentials.expired and self._credentials.refresh_token:
            try:
                self._credentials.refresh(GoogleAuthRequest())
                logger.info("Google OAuth token refreshed successfully")

                # Store refreshed tokens
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
                logger.error("Failed to refresh Google OAuth token: %s", e)
                # If refresh fails, tokens might be invalid for the current client_id.
                # We should clear local credentials so initialize() can try fallback.
                self._credentials = None
                # Optionally delete from DB if it's an "invalid_grant" error
                if "invalid_grant" in str(e).lower():
                    logger.warning("Invalid Google refresh token. Deleting from database.")
                    await await_if_needed(
                        self._db.delete("oauth_tokens", {"provider": "google"})
                    )
                raise RuntimeError(
                    "Google OAuth token refresh failed. Client may need to re-authorize."
                ) from e

        return self._credentials

    async def _get_service(self) -> Any:
        """Get or create the Google Calendar API service object.
        
        Attempts to initialize the service if it hasn't been created yet.
        """
        if self._service is None:
            await self.initialize()
        
        if self._service is None:
            raise RuntimeError(
                "Calendar service not initialized. "
                "This usually means Google OAuth is not configured. "
                "Visit the authorization URL in the system logs to fix this."
            )
        return self._service

    async def initialize(self) -> None:
        """Initialize the Google Calendar API service."""
        try:
            logger.info("Initializing Google Calendar service...")
            credentials = await self._get_credentials()
            
            if not credentials or not credentials.valid:
                logger.error("Google Calendar credentials invalid or missing")
                return

            # static_discovery=False fixes "Method doesn't allow unregistered callers" in some environments
            self._service = build("calendar", "v3", credentials=credentials, static_discovery=False)
            logger.info("Google Calendar service initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Calendar service: %s", e)
            # Don't re-raise to avoid crashing the whole system, but keep service None
            self._service = None

    async def get_auth_url(self) -> str:
        """Generate a new Google OAuth authorization URL."""
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
        return auth_url

    async def list_events(self, days: int = 7, *, _retry: bool = True) -> list[dict[str, Any]]:
        """List upcoming calendar events.

        Args:
            days: Number of days ahead to look (default 7, max 30).

        Returns:
            List of event dictionaries with id, summary, start, end, location.
        """
        days = min(max(days, 1), 30)
        service = await self._get_service()

        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)

        try:
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=100,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = []
            for item in result.get("items", []):
                start = safe_get(item.get("start", {}), "dateTime") or safe_get(
                    item.get("start", {}), "date", ""
                )
                end = safe_get(item.get("end", {}), "dateTime") or safe_get(
                    item.get("end", {}), "date", ""
                )

                events.append({
                    "id": item.get("id", ""),
                    "summary": item.get("summary", "(No title)"),
                    "start": start,
                    "end": end,
                    "location": item.get("location", ""),
                    "description": item.get("description", ""),
                })

            logger.info("Retrieved %d calendar events for next %d days", len(events), days)
            return events

        except HttpError as e:
            status = getattr(e.resp, "status", None)
            logger.error("Failed to list calendar events: %s", e)

            if status == 401 and _retry:
                # Token expired or revoked; try refresh once.
                self._credentials = None
                self._service = None
                await self.initialize()
                return await self.list_events(days, _retry=False)

            # 403 usually means OAuth client/scopes/API project mismatch.
            if status == 403:
                raise RuntimeError(
                    "Google Calendar access forbidden. Check OAuth client, scopes, and API access."
                ) from e

            raise
        except Exception as e:
            logger.error("Failed to list calendar events: %s", e)
            if _retry:
                self._credentials = None
                self._service = None
                await self.initialize()
                return await self.list_events(days, _retry=False)
            raise

    async def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        location: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Create a new calendar event.

        Args:
            summary: Event title/summary.
            start: Start time in ISO 8601 format.
            end: End time in ISO 8601 format.
            location: Event location (optional).

        Returns:
            Created event dict with id, summary, start, end, location. None on failure.
        """
        service = await self._get_service()

        event_body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }

        if location:
            event_body["location"] = location

        try:
            result = (
                service.events()
                .insert(calendarId="primary", body=event_body)
                .execute()
            )

            logger.info("Created calendar event: %s (ID: %s)", summary, result.get("id"))

            return {
                "id": result.get("id", ""),
                "summary": result.get("summary", ""),
                "start": safe_get(result.get("start", {}), "dateTime", ""),
                "end": safe_get(result.get("end", {}), "dateTime", ""),
                "location": result.get("location", ""),
            }

        except Exception as e:
            logger.error("Failed to create calendar event: %s", e)
            return None

    async def update_event(
        self,
        event_id: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update an existing calendar event.

        Args:
            event_id: Google Calendar event ID.
            updates: Dictionary of fields to update. Supported keys:
                summary, start, end, location, description.

        Returns:
            Updated event dict, or None on failure.
        """
        service = await self._get_service()

        try:
            # Fetch existing event
            existing = (
                service.events()
                .get(calendarId="primary", eventId=event_id)
                .execute()
            )

            # Apply updates
            if "summary" in updates:
                existing["summary"] = updates["summary"]
            if "start" in updates:
                existing["start"] = {"dateTime": updates["start"]}
            if "end" in updates:
                existing["end"] = {"dateTime": updates["end"]}
            if "location" in updates:
                existing["location"] = updates["location"]
            if "description" in updates:
                existing["description"] = updates["description"]

            result = (
                service.events()
                .update(calendarId="primary", eventId=event_id, body=existing)
                .execute()
            )

            logger.info("Updated calendar event: %s", event_id)

            return {
                "id": result.get("id", ""),
                "summary": result.get("summary", ""),
                "start": safe_get(result.get("start", {}), "dateTime", ""),
                "end": safe_get(result.get("end", {}), "dateTime", ""),
                "location": result.get("location", ""),
            }

        except Exception as e:
            logger.error("Failed to update calendar event %s: %s", event_id, e)
            return None

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event.

        Args:
            event_id: Google Calendar event ID to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        service = await self._get_service()

        try:
            service.events().delete(
                calendarId="primary", eventId=event_id
            ).execute()

            logger.info("Deleted calendar event: %s", event_id)
            return True

        except Exception as e:
            logger.error("Failed to delete calendar event %s: %s", event_id, e)
            return False

    async def get_next_event(self) -> Optional[dict[str, Any]]:
        """Get the next upcoming calendar event.

        Returns:
            The next event dict, or None if no upcoming events.
        """
        events = await self.list_events(days=7)
        if events:
            return events[0]
        return None

    async def sync_events_to_cache(self) -> int:
        """Sync upcoming events to the Supabase events_cache table.

        Fetches events for the next 7 days and upserts them into the cache.
        Used by the reminder scheduler to check for upcoming events.

        Returns:
            Number of events synced.
        """
        try:
            events = await self.list_events(days=7)
            synced = 0

            for event in events:
                event_id = event.get("id", "")
                if not event_id:
                    continue

                await await_if_needed(
                    self._db.upsert(
                        "events_cache",
                        {
                            "google_event_id": event_id,
                            "summary": event.get("summary", ""),
                            "location": event.get("location", ""),
                            "start_time": event.get("start", ""),
                            "end_time": event.get("end", ""),
                            "synced_at": datetime.now(timezone.utc).isoformat(),
                        },
                        on_conflict="google_event_id",
                    )
                )
                synced += 1

            logger.info("Synced %d events to cache", synced)
            return synced

        except Exception as e:
            logger.error("Failed to sync events to cache: %s", e)
            return 0
