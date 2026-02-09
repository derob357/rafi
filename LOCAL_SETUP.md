# Local Setup Guide (macOS)

This guide covers running Rafi on your local machine for rapid development and testing.

## 1. Prerequisites
- Python 3.11+
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
