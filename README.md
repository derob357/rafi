# Rafi

Rafi is a conversational assistant platform split into two packages: `rafi_assistant` builds the experience you use via Telegram, email, and voice, and `rafi_deploy` orchestrates new installations, provisioning, and onboarding flows.

## Repository layout
- `rafi_assistant/`: core assistant, scheduling, services, and voice/Telegram integrations. Now includes ADA-parity features like 3D CAD generation, autonomous web browsing, vision capture, and native desktop automation.
- `rafi_deploy/`: deployment helpers, onboarding tooling, and CLI wrappers for provisioning cloud resources.
- `docs/branch-protection.md`: recommended branch protection settings for `main`.
- `.github/workflows/ci.yml`: CI pipeline that runs tests for both packages on pushes and pull requests.

## Getting started
1. Install Python 3.11.
2. Copy `rafi_assistant/config/client_config.example.yaml` and `rafi_deploy/templates/client_config.template.yaml` to the locations your deployment needs, then populate API keys and service credentials.
3. Create a `.env` file in `rafi_assistant/` (and another inside `rafi_deploy/` if you store secrets there) to surface private values to the code. Both entry points automatically load `.env` via `python-dotenv`, so local runs and GitHub Actions will pick up the same variables as long as the file exists or the runner injects them via repository secrets.

### Install dependencies
```bash
python -m pip install --upgrade pip
python -m pip install -r rafi_assistant/requirements.txt
python -m pip install -r rafi_deploy/requirements.txt
```

### Run tests
- Assistant: `cd rafi_assistant && pytest`
- Deploy tooling: `cd rafi_deploy && pytest`

### Local Testing & Development
To run the full assistant with the Desktop UI on your local machine:
1. `cd rafi_assistant`
2. `cloudflared tunnel --url http://localhost:8000` (for webhooks)
3. `python run_local.py`

## CI and QA
All pushes and pull requests targeting `main` trigger the GitHub Actions workflow defined in `.github/workflows/ci.yml`. The workflow installs each package's dependencies and runs its `pytest` suite so that both directories are exercised on every merge.

## Branch protection
Follow the steps in `docs/branch-protection.md` to require the `CI` status check, enforce pull request reviews, and keep `main` safe.

## Secrets & configuration
- Store API credentials (OpenAI, Anthropic, Deepgram, Twilio, Supabase, etc.) as GitHub repository secrets and inject them into workflows via the `.env` files.
- Avoid checking secrets into source control; if you need to share example values, keep them in `*example*.yaml` files only.