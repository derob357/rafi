---
name: email
description: Read, search, and send emails via Gmail.
tools:
  - read_emails
  - search_emails
  - send_email
requires:
  env:
    - GOOGLE_CLIENT_ID
    - GOOGLE_CLIENT_SECRET
---

# Email Skill

Use these tools to manage the user's Gmail inbox.

- `read_emails`: Get recent emails, optionally filtered to unread only.
- `search_emails`: Search using Gmail query syntax (from:, subject:, after:, etc.).
- `send_email`: Send an email. Always confirm with the user before sending.
