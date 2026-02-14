"""Google integration diagnostics for rafi_assistant.

Checks environment/config alignment for Calendar OAuth and validates
refresh-token exchange + Calendar API reachability.

Usage:
  cd rafi_assistant
  python scripts/google_integration_diagnose.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1"


def _mask(value: str) -> str:
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _require_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _print_kv(key: str, value: Any) -> None:
    print(f"- {key}: {value}")


def _fail(msg: str) -> None:
    print(f"\nDIAGNOSIS: FAIL\n{msg}")
    sys.exit(1)


def _load_local_env() -> None:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        load_dotenv(override=False)


def main() -> None:
    _load_local_env()

    _print_header("Environment")
    client_id = _require_env("GOOGLE_CLIENT_ID")
    client_secret = _require_env("GOOGLE_CLIENT_SECRET")
    refresh_token = _require_env("GOOGLE_REFRESH_TOKEN")

    _print_kv("GOOGLE_CLIENT_ID", _mask(client_id))
    _print_kv("GOOGLE_CLIENT_SECRET", _mask(client_secret))
    _print_kv("GOOGLE_REFRESH_TOKEN", _mask(refresh_token))

    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", client_id),
            ("GOOGLE_CLIENT_SECRET", client_secret),
            ("GOOGLE_REFRESH_TOKEN", refresh_token),
        )
        if not value
    ]
    if missing:
        _fail(f"Missing required env vars: {', '.join(missing)}")

    _print_header("Token Exchange")
    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    with httpx.Client(timeout=20.0) as client:
        token_resp = client.post(TOKEN_URL, data=token_payload)

    _print_kv("token_http_status", token_resp.status_code)
    if token_resp.status_code != 200:
        try:
            body = token_resp.json()
        except Exception:
            body = {"raw": token_resp.text[:500]}
        _print_kv("token_error", json.dumps(body))
        _fail("Refresh-token exchange failed. Verify client id/secret/refresh token alignment.")

    token_json = token_resp.json()
    access_token = token_json.get("access_token", "")
    scope = token_json.get("scope", "")

    _print_kv("access_token", _mask(access_token))
    _print_kv("scope", scope or "<not_returned>")
    if not access_token:
        _fail("No access_token returned from token exchange.")

    _print_header("Calendar API Probe")
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=20.0) as client:
        cal_resp = client.get(CALENDAR_LIST_URL, headers=headers)

    _print_kv("calendar_http_status", cal_resp.status_code)

    if cal_resp.status_code == 200:
        data = cal_resp.json()
        items = data.get("items", [])
        _print_kv("calendar_list_items", len(items))
        print("\nDIAGNOSIS: PASS\nGoogle Calendar OAuth integration looks healthy.")
        return

    try:
        error_body = cal_resp.json()
    except Exception:
        error_body = {"raw": cal_resp.text[:1000]}

    _print_kv("calendar_error", json.dumps(error_body))

    hint = (
        "Calendar probe failed. Common fixes: ensure Calendar API is enabled in the same project as the OAuth client, "
        "consent screen/test-user settings are valid, and refresh token was generated for this exact client."
    )
    _fail(hint)


if __name__ == "__main__":
    main()
