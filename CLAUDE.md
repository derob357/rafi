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
- **WhatsApp** → Twilio webhook → `MessageProcessor` → LLM → response via Twilio REST
- **Voice calls** → Twilio → ElevenLabs Conversational AI (STT+LLM+TTS) → tools → transcript to Supabase
- **Async transcription** (Telegram voice messages) → Deepgram
- **Proactive notifications** → APScheduler → HeartbeatRunner → `ChannelManager.send_to_preferred()` (Telegram, WhatsApp, or any configured adapter)

Each client has their own: Supabase project, Telegram bot, Twilio phone number.

### OpenClaw-Inspired 4-Pillar Architecture

The assistant uses an architecture inspired by OpenClaw's four core pillars:

1. **Memory System** — Markdown files (`memory/SOUL.md`, `USER.md`, `MEMORY.md`, `AGENTS.md`, `HEARTBEAT.md`) as source of truth. `MemoryFileService` composes system prompts from these files. Supabase pgvector serves as the search index with `min_score=0.35` filtering.

2. **Heartbeat** — `HeartbeatRunner` runs every 30 minutes via APScheduler. Gathers context from email, calendar, tasks, and weather; sends to LLM for evaluation. Respects quiet hours, deduplicates alerts (24h window), delivers via `ChannelManager`.

3. **Channel Adapters** — `ChannelAdapter` ABC in `src/channels/base.py`. All platforms normalize messages into `ChannelMessage` dataclass. `MessageProcessor` provides a shared LLM orchestration pipeline across channels. Implemented: Telegram, WhatsApp (Twilio). Stubs: Slack, Discord.

4. **Skills Registry** — `skills/*/SKILL.md` files with YAML frontmatter define tool groups. `SkillLoader` discovers, parses, and filters skills by env var requirements. `ToolRegistry` provides dynamic dispatch with OpenAI schema co-registration.

### Key Components

- **ToolRegistry** (`src/tools/tool_registry.py`) — Central tool dispatch. `register_tool(name, func, description, schema)` and `invoke(name, **kwargs) -> str`. All tool functions return formatted strings. Replaces the old hardcoded tool switch.
- **MessageProcessor** (`src/channels/processor.py`) — Shared LLM pipeline: sanitize → injection check → store → context → LLM chat → tool calls → return.
- **ChannelManager** (`src/channels/manager.py`) — Adapter lifecycle and message routing. `send_to_preferred()` for proactive notifications with fallback.
- **MemoryFileService** (`src/services/memory_files.py`) — Loads markdown memory files, builds system prompts, writes daily session logs.
- **HeartbeatRunner** (`src/scheduling/heartbeat.py`) — Proactive check loop with quiet hours, dedup, and LLM evaluation.

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
pytest tests/unit/ -v                            # Unit tests (314 tests)
pytest tests/security/ -m security -v            # Security tests only
pytest tests/integration/ -m integration -v      # Integration tests (needs API keys)
pytest tests/e2e/ -m e2e -v                      # E2E tests (needs full environment)
pytest --cov=src --cov-report=html                # Full coverage report

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

## Key Directory Structure

```
rafi_assistant/
├── memory/                    # Markdown memory files (source of truth)
│   ├── SOUL.md               # Agent personality and values
│   ├── USER.md               # User profile and preferences
│   ├── MEMORY.md             # Long-term curated memories
│   ├── AGENTS.md             # Agent behavior rules
│   ├── HEARTBEAT.md          # Proactive check checklist
│   └── daily/                # Auto-generated daily session logs
├── skills/                    # Skill definitions (YAML frontmatter + instructions)
│   ├── calendar/SKILL.md
│   ├── email/SKILL.md
│   ├── tasks/SKILL.md
│   └── ... (10 skills total)
├── src/
│   ├── channels/             # Channel adapter system
│   │   ├── base.py           # ChannelAdapter ABC + ChannelMessage
│   │   ├── processor.py      # MessageProcessor (shared LLM pipeline)
│   │   ├── manager.py        # ChannelManager (lifecycle + routing)
│   │   ├── telegram.py       # TelegramAdapter
│   │   ├── whatsapp.py       # WhatsAppAdapter (Twilio)
│   │   ├── slack.py          # Stub
│   │   └── discord.py        # Stub
│   ├── skills/               # Skill loader system
│   │   ├── loader.py         # discover_skills(), filter_eligible()
│   │   └── types.py          # Skill dataclass
│   ├── scheduling/
│   │   ├── scheduler.py      # RafiScheduler (APScheduler wrapper)
│   │   └── heartbeat.py      # HeartbeatRunner
│   ├── tools/
│   │   └── tool_registry.py  # ToolRegistry (dynamic dispatch)
│   ├── services/
│   │   ├── memory_files.py   # MemoryFileService
│   │   ├── memory_service.py # MemoryService (Supabase pgvector)
│   │   └── ...               # Calendar, Email, Task, Note, Weather, etc.
│   ├── bot/
│   │   └── telegram_bot.py   # Legacy TelegramBot (uses ToolRegistry)
│   ├── llm/
│   │   ├── provider.py       # LLMProvider interface
│   │   ├── llm_manager.py    # LLMManager (multi-provider, failover)
│   │   └── tool_definitions.py # OpenAI tool schemas + TOOL_SCHEMA_MAP
│   └── main.py               # FastAPI app, service wiring, tool registration
```

## Key Patterns

- **Config validation**: All config loaded through pydantic models in `src/config/loader.py`. App refuses to start on invalid config.
- **Input sanitization**: All external text goes through `src/security/sanitizer.py` before reaching LLM or database. This includes Telegram messages, voice transcriptions, and config values.
- **Null safety**: Use `safe_get()` and `safe_list_get()` from `src/security/validators.py` for all external data access.
- **LLM provider abstraction**: `src/llm/provider.py` defines the interface. `LLMManager` in `src/llm/llm_manager.py` orchestrates multiple providers (OpenAI, Anthropic, Groq, Gemini) with runtime switching via Telegram `/provider` command and automatic failover. Embeddings always route to OpenAI.
- **Tool registration**: Tools are registered in `main.py` as formatted wrapper functions that call services and return strings. Each tool gets an OpenAI schema from `TOOL_SCHEMA_MAP`. The `ToolRegistry.invoke()` method handles dispatch.
- **Channel-agnostic processing**: `MessageProcessor` in `src/channels/processor.py` provides the same LLM pipeline for all channels. Channel adapters normalize messages into `ChannelMessage` and delegate to the processor.
- **Proactive notifications**: `HeartbeatRunner` and scheduler use `ChannelManager.send_to_preferred()` which tries the preferred channel and falls back to any available adapter.
- **Error handling**: Every external API call has retry logic with exponential backoff. Failed voice calls fall back to Telegram text. See Error Handling Strategies in RAFI_SPEC.md.
- **Quiet hours**: All outbound call logic and heartbeat checks respect quiet hours from config.

## Security Requirements

- All Supabase queries use parameterized inputs (no raw SQL)
- Prompt injection detection on all user input before LLM
- Twilio webhook signature validation on every request
- Telegram user_id authorization on every message
- OAuth tokens encrypted with Fernet at rest
- API keys passed as env vars, never in Docker images

## Test Markers

Tests use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.security`, `@pytest.mark.e2e`. Integration and E2E tests skip automatically without live API credentials.
