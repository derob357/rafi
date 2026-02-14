---
name: calendar
description: Manage Google Calendar events — read, create, update, and delete.
tools:
  - read_calendar
  - create_event
  - update_event
  - delete_event
  - get_google_auth_url
requires:
  env:
    - GOOGLE_CLIENT_ID
    - GOOGLE_CLIENT_SECRET
---

# Calendar Skill

Use these tools to manage the user's Google Calendar.

- `read_calendar`: List upcoming events for a number of days (default 7).
- `create_event`: Create events with summary, start/end times (ISO 8601), and optional location.
- `update_event`: Modify an existing event by its ID.
- `delete_event`: Cancel an event by its ID.
- `get_google_auth_url`: Get the OAuth URL if calendar needs re-authorization.

Always use ISO 8601 format for dates/times (e.g., 2024-01-15T14:00:00-05:00).
