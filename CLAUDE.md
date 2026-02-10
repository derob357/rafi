# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Rafi is a template-based personal AI assistant platform. It consists of three repos in this directory:

- **rafi_assistant/** — The AI assistant bot (Python, Docker, PySide6). Includes 3D CAD, Web Automation, Screen Control, and Vision.
- **rafi_deploy/** — CLI tooling for onboarding clients and deploying assistant instances.
- **rafi_vision/** — (Integrated into rafi_assistant) 3D gesture-controlled data visualization.

Full spec: `RAFI_SPEC.md`

## Architecture

Each client runs a Docker container on a shared EC2 t3.micro. Communication flows:
- **Telegram text/voice** → python-telegram-bot → LLM (OpenAI/Anthropic/Groq/Gemini, runtime switchable) → response
- **Voice calls** → Twilio → ElevenLabs Conversational AI (STT+LLM+TTS) → tools → transcript to Supabase
- **Async transcription** (Telegram voice messages) → Deepgram
- **Proactive calls** → APScheduler → Twilio outbound (respects quiet hours, falls back to Telegram)

Each client has their own: Supabase project, Telegram bot, Twilio phone number.

## Build & Run Commands

### rafi_assistant
```bash
# Install dependencies
pip install -r rafi_assistant/requirements.txt

# Run locally (requires config.yaml)
RAFI_CONFIG_PATH=./config.yaml uvicorn src.main:app --host 0.0.0.0 --port 8000

# Docker build and run
cd rafi_assistant && docker build -t rafi_assistant . && docker-compose up

# Run tests
cd rafi_assistant
pytest tests/unit/ -m unit -v                  # Unit tests only
pytest tests/security/ -m security -v          # Security tests only
pytest tests/integration/ -m integration -v    # Integration tests (needs API keys)
pytest tests/e2e/ -m e2e -v                    # E2E tests (needs full environment)
pytest --cov=src --cov-report=html              # Full coverage report

# Type checking
mypy --strict src/

# Generate DEPENDENCIES.md
python scripts/generate_deps.py
```

### rafi_deploy
```bash
# Install dependencies
pip install -r rafi_deploy/requirements.txt

# CLI commands
python -m src.cli onboard --audio /path/to/recording.wav
python -m src.cli extract --transcript /path/to/transcript.txt --output config.yaml
python -m src.cli deploy --config /path/to/client_config.yaml
python -m src.cli stop --client "client_name"
python -m src.cli restart --client "client_name"
python -m src.cli health --client "client_name"

# Run tests
cd rafi_deploy
pytest tests/ -v
```

## Key Patterns

- **Config validation**: All config loaded through pydantic models in `src/config/loader.py`. App refuses to start on invalid config.
- **Input sanitization**: All external text goes through `src/security/sanitizer.py` before reaching LLM or database. This includes Telegram messages, voice transcriptions, and config values.
- **Null safety**: Use `safe_get()` and `safe_list_get()` from `src/security/validators.py` for all external data access.
- **LLM provider abstraction**: `src/llm/provider.py` defines the interface. `LLMManager` in `src/llm/llm_manager.py` orchestrates multiple providers (OpenAI, Anthropic, Groq, Gemini) with runtime switching via Telegram `/provider` command and automatic failover. Embeddings always route to OpenAI.
- **Error handling**: Every external API call has retry logic with exponential backoff. Failed voice calls fall back to Telegram text. See Error Handling Strategies in RAFI_SPEC.md.
- **Quiet hours**: All outbound call logic checks quiet hours immediately before dialing, not just at schedule time.

## Security Requirements

- All Supabase queries use parameterized inputs (no raw SQL)
- Prompt injection detection on all user input before LLM
- Twilio webhook signature validation on every request
- Telegram user_id authorization on every message
- OAuth tokens encrypted with Fernet at rest
- API keys passed as env vars, never in Docker images

## Test Markers

Tests use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.security`, `@pytest.mark.e2e`. Integration and E2E tests skip automatically without live API credentials.
