# Google Integration Runbook (Calendar/Gmail)

This runbook fixes and verifies Google OAuth integration for `rafi_assistant`, including the common failure:

- `403 Method doesn't allow unregistered callers`

---

## 1) What this error usually means

For Calendar/Gmail user data, Google expects a valid OAuth caller identity.

You typically see this error when one of these is true:

- Calendar API is not enabled in the same GCP project as your OAuth client.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` do not belong to the same OAuth client + project.
- OAuth consent/app audience is misconfigured (test users missing, wrong publishing mode).
- Refresh token is stale/revoked or from a previous client secret/client ID.
- Redirect/client type mismatch (Desktop vs Web flow confusion).

---

## 2) Exact setup (do this in order)

### Step A — Pick one project and enable APIs

1. In Google Cloud Console, select your intended project.
2. Enable:
   - Google Calendar API
   - Gmail API (if email integration is also needed)

CLI check:

```bash
gcloud config get-value project
gcloud services list --enabled | grep -E "calendar-json.googleapis.com|gmail.googleapis.com"
```

Enable if missing:

```bash
gcloud services enable calendar-json.googleapis.com gmail.googleapis.com
```

### Step B — Configure OAuth consent screen

In Google Cloud Console -> APIs & Services -> OAuth consent screen:

- Set audience correctly (Internal/External).
- If External + Testing, add your Google account under **Test users**.
- Ensure scopes include needed Calendar/Gmail scopes.

### Step C — Create credentials correctly

In APIs & Services -> Credentials:

- Create OAuth client credentials for your flow.
  - Local/installed flow: Desktop app
  - Hosted callback flow: Web application with exact redirect URIs

Use this client ID/secret in `.env` or config.

### Step D — Generate fresh refresh token (important)

After changing scopes/client/consent settings, generate a new refresh token and replace the old one.

Required env vars:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
```

---

## 3) Verify with direct API checks

### 3.1 Exchange refresh token for access token

```bash
curl -s -X POST https://oauth2.googleapis.com/token \
  -d "client_id=$GOOGLE_CLIENT_ID" \
  -d "client_secret=$GOOGLE_CLIENT_SECRET" \
  -d "refresh_token=$GOOGLE_REFRESH_TOKEN" \
  -d "grant_type=refresh_token"
```

Expected: JSON containing `access_token`.

### 3.2 Validate token against Calendar

```bash
ACCESS_TOKEN="<token_from_previous_step>"
curl -i -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1"
```

Expected: HTTP 200 with calendar list data.

If this fails with 403, the issue is still credentials/project/consent mismatch.

---

## 4) Validate in rafi_assistant

From `rafi_assistant`:

```bash
pytest tests/integration/test_google_calendar_env.py -q
```

If passing, rerun all integration tests:

```bash
pytest tests/integration -q
```

---

## 5) Environment hygiene best practices

- Use separate Google projects and OAuth clients for `dev`, `staging`, `prod`.
- Do not share refresh tokens across environments.
- Rotate secrets deliberately and regenerate refresh tokens after rotation.
- Keep a credential matrix per env:
  - project id
  - enabled APIs
  - oauth client id
  - consent screen audience
  - scopes
  - test users

---

## 6) Fast triage checklist

- [ ] Calendar API enabled in active project
- [ ] OAuth client and refresh token from same project/client
- [ ] Correct client type and redirect settings
- [ ] Consent screen configured and account is allowed (test user if needed)
- [ ] Refresh token exchange returns access token
- [ ] Direct Calendar call with bearer token returns 200
- [ ] `test_google_calendar_env.py` passes
