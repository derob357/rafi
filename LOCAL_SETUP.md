# Local Setup Guide (macOS)

This guide covers running Rafi on your local machine for rapid development and testing.

## 1. Prerequisites
- Python 3.11 or 3.12 recommended (CAD dependency `build123d` is currently incompatible with Python 3.13+ in this stack)
- [Cloudflare Tunnel CLI](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/installation/) (`brew install cloudflared`)
- System libraries for CAD/Vision:
  ```bash
  brew install opencv pango cairo libglvnd
  ```

## 2. Environment Setup
```bash
cd rafi_assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 3. Webhook Connectivity
Rafi requires a public URL for Twilio and Telegram. 

1. Start a tunnel:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
2. Copy the resulting `https://...` URL.
3. Update your `.env` in `rafi_assistant/`:
   ```env
   WEBHOOK_BASE_URL=https://your-unique-subdomain.trycloudflare.com
   ```

## 4. Running the App
Run the local runner, which starts the FastAPI server and the PySide6 UI in a shared event loop:
```bash
python run_local.py
```

## 5. macOS Permissions
- **Camera/Mic**: When you first toggle the camera/microphone in the UI, macOS will prompt for permission. Ensure you allow it for the terminal/IDE running the script.
- **Screen Recording**: Required for the `Share Screen` feature. If it fails, check `System Settings > Privacy & Security > Screen Recording`.

## 6. Testing CAD & Browser Tools
- **CAD**: Ensure you have `build123d` installed. Scripts generate STL files in your `/tmp` directory.
- **Browser**: Playwright will run in headless mode by default. You can change `headless=True` to `False` in `src/services/browser_service.py` for visual debugging.

## 7. Google Integration (Calendar/Gmail) — Exact Steps

1. In Google Cloud Console, select one project for local dev.
2. Enable APIs in that same project:
   - Google Calendar API
   - Gmail API (if using email skill)
3. Configure OAuth consent screen:
   - set audience (Internal/External)
   - if External + Testing, add your account under Test users
4. Create OAuth client credentials and set:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
5. Generate and set `GOOGLE_REFRESH_TOKEN` for this exact OAuth client.

Run diagnostics:

```bash
cd rafi_assistant
python scripts/google_integration_diagnose.py
```

Then validate integration test:

```bash
pytest tests/integration/test_google_calendar_env.py -q
```

For detailed troubleshooting, see `rafi_assistant/GOOGLE_INTEGRATION_RUNBOOK.md`.

## 8. Website Reading Capability (Rafi)

Rafi reads websites through `browse_web` using Playwright.

Prerequisites:

```bash
cd rafi_assistant
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Runtime behavior:
- `browse_web` now returns:
  - `title`
  - `content_preview` (first ~6000 chars of page text)
  - `screenshot`
- `search_web` returns top search results.

Quick verification:
1. Start app: `python run_local.py`
2. Ask Rafi: "Browse https://example.com and summarize it."
