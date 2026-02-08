"""Create and manage Supabase projects via the Management API.

Handles project creation, waiting for readiness, running database
migrations, enabling the pgvector extension, and project cleanup.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Supabase Management API base URL
MANAGEMENT_API_BASE = "https://api.supabase.com/v1"

# Polling configuration for project readiness
PROJECT_READY_POLL_INTERVAL = 10  # seconds
PROJECT_READY_TIMEOUT = 300  # seconds (5 minutes)

# Default database password length
DB_PASSWORD_LENGTH = 32

# Default region
DEFAULT_REGION = "us-east-1"

# Default plan
DEFAULT_PLAN = "free"

# Migrations SQL path (relative to rafi_assistant repo)
DEFAULT_MIGRATIONS_PATH = "src/db/migrations.sql"

# Built-in migrations SQL for creating all required tables
MIGRATIONS_SQL = """\
-- Enable pgvector extension for embedding storage
CREATE EXTENSION IF NOT EXISTS vector;

-- Messages table with embeddings for semantic memory
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    embedding vector(3072),
    source TEXT CHECK (source IN ('telegram_text', 'telegram_voice', 'twilio_call')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tasks table
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed')),
    due_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Notes table
CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Call logs table
CREATE TABLE IF NOT EXISTS call_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_sid TEXT,
    direction TEXT CHECK (direction IN ('inbound', 'outbound')),
    duration_seconds INTEGER,
    transcript TEXT,
    summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Settings table (key-value store)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OAuth tokens table (encrypted at rest by the application)
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    scopes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Events cache table for Google Calendar sync
CREATE TABLE IF NOT EXISTS events_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_event_id TEXT UNIQUE NOT NULL,
    summary TEXT,
    location TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    reminded BOOLEAN NOT NULL DEFAULT false,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages (source);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks (due_date);
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_logs_created_at ON call_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_cache_start_time ON events_cache (start_time);
CREATE INDEX IF NOT EXISTS idx_events_cache_google_event_id ON events_cache (google_event_id);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;
CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_notes_updated_at ON notes;
CREATE TRIGGER update_notes_updated_at
    BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_settings_updated_at ON settings;
CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_oauth_tokens_updated_at ON oauth_tokens;
CREATE TRIGGER update_oauth_tokens_updated_at
    BEFORE UPDATE ON oauth_tokens
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security on all tables
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE events_cache ENABLE ROW LEVEL SECURITY;

-- Create service-role-only policies (the assistant uses the service role key)
CREATE POLICY IF NOT EXISTS "Service role full access on messages"
    ON messages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "Service role full access on tasks"
    ON tasks FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "Service role full access on notes"
    ON notes FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "Service role full access on call_logs"
    ON call_logs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "Service role full access on settings"
    ON settings FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "Service role full access on oauth_tokens"
    ON oauth_tokens FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "Service role full access on events_cache"
    ON events_cache FOR ALL USING (true) WITH CHECK (true);
"""


class SupabaseProvisioningError(Exception):
    """Raised when Supabase project provisioning fails."""

    pass


def _get_management_token() -> str:
    """Get the Supabase Management API access token.

    Returns:
        The access token string.

    Raises:
        SupabaseProvisioningError: If the token is not set.
    """
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        raise SupabaseProvisioningError(
            "SUPABASE_ACCESS_TOKEN environment variable is not set. "
            "Generate a token at https://supabase.com/dashboard/account/tokens"
        )
    return token


def _get_organization_id() -> str:
    """Get the Supabase organization ID.

    Returns:
        The organization ID string.

    Raises:
        SupabaseProvisioningError: If the ID is not set.
    """
    org_id = os.environ.get("SUPABASE_ORG_ID")
    if not org_id:
        raise SupabaseProvisioningError(
            "SUPABASE_ORG_ID environment variable is not set. "
            "Find your organization ID in the Supabase dashboard."
        )
    return org_id


def _api_headers(token: str) -> dict[str, str]:
    """Build HTTP headers for the Management API.

    Args:
        token: The access token.

    Returns:
        Headers dictionary.
    """
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _generate_db_password() -> str:
    """Generate a secure random database password.

    Returns:
        A random password string.
    """
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(DB_PASSWORD_LENGTH))


def create_project(
    client_name: str,
    region: str = DEFAULT_REGION,
    plan: str = DEFAULT_PLAN,
) -> dict[str, str]:
    """Create a new Supabase project for a client.

    Creates the project, waits for it to become ready, runs database
    migrations, and enables the pgvector extension.

    Args:
        client_name: Sanitized client name (used in project name).
        region: AWS region for the project. Defaults to 'us-east-1'.
        plan: Supabase plan ('free' or 'pro'). Defaults to 'free'.

    Returns:
        Dictionary with keys:
            - 'project_id': Supabase project ID
            - 'url': Project API URL
            - 'anon_key': Anonymous API key
            - 'service_role_key': Service role API key
            - 'db_password': Database password

    Raises:
        SupabaseProvisioningError: If project creation, readiness check,
            or migration fails.
    """
    token = _get_management_token()
    org_id = _get_organization_id()
    headers = _api_headers(token)
    db_password = _generate_db_password()

    project_name = f"rafi-{client_name}"
    logger.info(
        "Creating Supabase project '%s' in region '%s'", project_name, region
    )

    # Step 1: Create the project
    create_payload = {
        "name": project_name,
        "organization_id": org_id,
        "region": region,
        "plan": plan,
        "db_pass": db_password,
    }

    try:
        response = httpx.post(
            f"{MANAGEMENT_API_BASE}/projects",
            headers=headers,
            json=create_payload,
            timeout=60.0,
        )
        response.raise_for_status()
        project_data = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response else "No response body"
        raise SupabaseProvisioningError(
            f"Failed to create Supabase project: {exc.response.status_code} - {body}"
        ) from exc
    except httpx.RequestError as exc:
        raise SupabaseProvisioningError(
            f"Network error creating Supabase project: {exc}"
        ) from exc

    project_id = project_data.get("id")
    if not project_id:
        raise SupabaseProvisioningError(
            "Supabase API did not return a project ID"
        )

    logger.info("Project created with ID: %s", project_id)

    # Step 2: Wait for project to be ready
    _wait_for_project_ready(project_id, token, headers)

    # Step 3: Get API keys
    api_keys = _get_api_keys(project_id, token, headers)

    # Step 4: Run migrations
    _run_migrations(project_id, db_password, token, headers)

    project_url = f"https://{project_id}.supabase.co"
    result = {
        "project_id": project_id,
        "url": project_url,
        "anon_key": api_keys.get("anon_key", ""),
        "service_role_key": api_keys.get("service_role_key", ""),
        "db_password": db_password,
    }

    logger.info(
        "Supabase project fully provisioned: %s (%s)", project_name, project_url
    )
    print(f"Supabase project created: {project_name}")
    print(f"  URL: {project_url}")
    print(f"  Project ID: {project_id}")

    return result


def _wait_for_project_ready(
    project_id: str, token: str, headers: dict[str, str]
) -> None:
    """Poll until the Supabase project status is ACTIVE_HEALTHY.

    Args:
        project_id: The Supabase project ID.
        token: The management API token.
        headers: HTTP headers.

    Raises:
        SupabaseProvisioningError: If the project does not become ready
            within the timeout period.
    """
    logger.info("Waiting for project %s to become ready...", project_id)
    start_time = time.monotonic()

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > PROJECT_READY_TIMEOUT:
            raise SupabaseProvisioningError(
                f"Project {project_id} did not become ready within "
                f"{PROJECT_READY_TIMEOUT} seconds"
            )

        try:
            response = httpx.get(
                f"{MANAGEMENT_API_BASE}/projects/{project_id}",
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            project = response.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("Error checking project status: %s", exc)
            time.sleep(PROJECT_READY_POLL_INTERVAL)
            continue

        status = project.get("status", "")
        logger.debug("Project status: %s (%.0fs elapsed)", status, elapsed)

        if status == "ACTIVE_HEALTHY":
            logger.info("Project %s is ready (%.0fs)", project_id, elapsed)
            return

        if status in ("REMOVED", "PAUSED", "INACTIVE"):
            raise SupabaseProvisioningError(
                f"Project {project_id} entered unexpected status: {status}"
            )

        time.sleep(PROJECT_READY_POLL_INTERVAL)


def _get_api_keys(
    project_id: str, token: str, headers: dict[str, str]
) -> dict[str, str]:
    """Retrieve the API keys for a Supabase project.

    Args:
        project_id: The Supabase project ID.
        token: The management API token.
        headers: HTTP headers.

    Returns:
        Dict with 'anon_key' and 'service_role_key'.

    Raises:
        SupabaseProvisioningError: If the keys cannot be retrieved.
    """
    try:
        response = httpx.get(
            f"{MANAGEMENT_API_BASE}/projects/{project_id}/api-keys",
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        keys_list = response.json()
    except httpx.HTTPStatusError as exc:
        raise SupabaseProvisioningError(
            f"Failed to retrieve API keys: {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise SupabaseProvisioningError(
            f"Network error retrieving API keys: {exc}"
        ) from exc

    result: dict[str, str] = {}

    if isinstance(keys_list, list):
        for key_entry in keys_list:
            name = key_entry.get("name", "")
            api_key = key_entry.get("api_key", "")
            if "anon" in name.lower():
                result["anon_key"] = api_key
            elif "service" in name.lower():
                result["service_role_key"] = api_key

    if not result.get("anon_key") or not result.get("service_role_key"):
        logger.warning(
            "Could not find both API keys. Found: %s",
            list(result.keys()),
        )

    return result


def _run_migrations(
    project_id: str,
    db_password: str,
    token: str,
    headers: dict[str, str],
) -> None:
    """Run database migrations on the Supabase project.

    Uses the Supabase Management API SQL endpoint to execute the
    migration SQL that creates all required tables and extensions.

    Args:
        project_id: The Supabase project ID.
        db_password: The database password.
        token: The management API token.
        headers: HTTP headers.

    Raises:
        SupabaseProvisioningError: If migrations fail.
    """
    logger.info("Running database migrations on project %s", project_id)

    try:
        response = httpx.post(
            f"{MANAGEMENT_API_BASE}/projects/{project_id}/database/query",
            headers=headers,
            json={"query": MIGRATIONS_SQL},
            timeout=120.0,
        )
        response.raise_for_status()
        logger.info("Database migrations completed successfully")

    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response else "No response body"
        raise SupabaseProvisioningError(
            f"Migration failed: {exc.response.status_code} - {body}"
        ) from exc
    except httpx.RequestError as exc:
        raise SupabaseProvisioningError(
            f"Network error running migrations: {exc}"
        ) from exc


def delete_project(project_id: str) -> None:
    """Delete a Supabase project.

    This permanently deletes the project and all its data. This action
    cannot be undone.

    Args:
        project_id: The Supabase project ID to delete.

    Raises:
        SupabaseProvisioningError: If deletion fails.
    """
    token = _get_management_token()
    headers = _api_headers(token)

    logger.warning("Deleting Supabase project: %s", project_id)

    try:
        response = httpx.delete(
            f"{MANAGEMENT_API_BASE}/projects/{project_id}",
            headers=headers,
            timeout=60.0,
        )
        response.raise_for_status()
        logger.info("Supabase project %s deleted", project_id)
        print(f"Supabase project deleted: {project_id}")

    except httpx.HTTPStatusError as exc:
        raise SupabaseProvisioningError(
            f"Failed to delete project {project_id}: {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise SupabaseProvisioningError(
            f"Network error deleting project: {exc}"
        ) from exc


def get_project_status(project_id: str) -> dict[str, Any]:
    """Get the current status of a Supabase project.

    Args:
        project_id: The Supabase project ID.

    Returns:
        Dictionary with project status information.

    Raises:
        SupabaseProvisioningError: If the status check fails.
    """
    token = _get_management_token()
    headers = _api_headers(token)

    try:
        response = httpx.get(
            f"{MANAGEMENT_API_BASE}/projects/{project_id}",
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as exc:
        raise SupabaseProvisioningError(
            f"Failed to get project status: {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise SupabaseProvisioningError(
            f"Network error checking project status: {exc}"
        ) from exc
