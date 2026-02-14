# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Required: Read All Context Files on Start

Before doing any work, read `RAFI_SPEC.md` for the full project specification.

## Project Overview

Rafi is a template-based personal AI assistant platform. Three sub-projects:

- **rafi_assistant/** — The AI assistant (Python, FastAPI, Docker). 11 skills, 25+ tools, 4 channels, 4 LLM providers.
- **rafi_deploy/** — CLI tooling for onboarding and deploying instances.
- **myOpenClaw/** — Reference architecture (read-only).

## Skill Routing

USE WHEN patterns for directing work to the right area:

| Pattern | Skill/Area | Key Files |
|---------|-----------|-----------|
| "add a tool", "new tool" | Tool system | `src/tools/tool_registry.py`, `src/llm/tool_definitions.py`, `src/main.py` |
| "channel", "telegram", "whatsapp" | Channel adapters | `src/channels/`, `src/main.py` |
| "memory", "remember", "context" | Memory system | `src/services/memory_service.py`, `src/services/memory_files.py`, `memory/` |
| "heartbeat", "proactive", "notification" | Heartbeat | `src/scheduling/heartbeat.py`, `memory/HEARTBEAT.md` |
| "LLM", "provider", "model" | LLM layer | `src/llm/llm_manager.py`, `src/llm/provider.py`, `src/llm/*.py` |
| "config", "settings", "env" | Configuration | `src/config/loader.py`, `config.yaml`, `.env` |
| "skill", "SKILL.md" | Skills registry | `skills/*/SKILL.md`, `src/skills/loader.py` |
| "schedule", "briefing", "reminder" | Scheduling | `src/scheduling/` |
| "voice", "call", "twilio" | Voice pipeline | `src/voice/`, `src/main.py` (twilio routes) |
| "security", "injection", "sanitize" | Security | `src/security/` |
| "test" | Testing | `tests/unit/`, `tests/integration/`, `tests/security/` |
| "deploy", "docker" | Deployment | `Dockerfile`, `docker-compose.yml`, `deployment/` |
| "ISC", "verify", "criteria" | Algorithm (ISC) | `src/services/isc_service.py`, `src/channels/processor.py` |
| "learning", "rating", "feedback" | Learning system | `src/services/learning_service.py` |
| "dashboard", "observability" | Dashboard | `src/main.py` (dashboard routes) |
| "MCP", "mcp server" | MCP server | `src/mcp/` |

## Architecture

### OpenClaw-Inspired 4-Pillar Architecture + PAI Algorithm

The assistant uses four core pillars enhanced with PAI-inspired concepts:

1. **Memory System** — Markdown files (`memory/SOUL.md`, `USER.md`, `MEMORY.md`, `AGENTS.md`, `HEARTBEAT.md`) as source of truth. `MemoryFileService` composes system prompts. Supabase pgvector serves as the search index. Automated memory promotion moves insights from daily logs to long-term memory.

2. **Heartbeat** — `HeartbeatRunner` runs every 30 minutes via APScheduler. Gathers context, evaluates with LLM, respects quiet hours, deduplicates alerts. Learning-based priority adjustment from user feedback.

3. **Channel Adapters** — `ChannelAdapter` ABC. All platforms normalize to `ChannelMessage`. `MessageProcessor` provides shared LLM orchestration with ISC-driven task execution and verification. Implemented: Telegram, WhatsApp. Stubs: Slack, Discord.

4. **Skills Registry** — `skills/*/SKILL.md` with YAML frontmatter. `SkillLoader` discovers and filters by env vars. `ToolRegistry` provides dynamic dispatch.

### ISC (Ideal State Criteria) Pipeline

Inspired by PAI's Algorithm, the `MessageProcessor` now follows:
1. **Classify** — Detect if the message needs tool use (FULL mode) or is conversational (MINIMAL)
2. **Generate ISC** — For FULL mode, generate binary-testable success criteria before executing
3. **Execute** — Run tools against the criteria
4. **Verify** — Check each criterion with evidence before responding
5. **Learn** — Capture user satisfaction signals for continuous improvement

### Learning System

- Rating detection in user messages (explicit 1-10, implicit sentiment)
- Feedback stored in Supabase `feedback` table
- Periodic analysis generates improvement insights
- Insights feed back into system prompt as behavioral adjustments

## Build & Run Commands

```bash
# Install dependencies
pip install -r rafi_assistant/requirements.txt

# Run locally (IMPORTANT: stop EC2 instance first to avoid Telegram 409 conflicts)
RAFI_CONFIG_PATH=./config.yaml uvicorn src.main:app --host 0.0.0.0 --port 8000

# Docker (local)
cd rafi_assistant && docker build -t rafi_assistant . && docker-compose up

# Tests
cd rafi_assistant
pytest tests/unit/ -v
pytest tests/security/ -m security -v
pytest tests/integration/ -m integration -v
pytest --cov=src --cov-report=html
```

## EC2 Deployment (Production)

Rafi runs 24/7 on AWS EC2 (`i-056d98e041c0bc01c`, t4g.small ARM64, us-east-2).
Cloudflare tunnel routes `rafi.intentionai.ai` to the EC2 containers.

```bash
# SSH into EC2
ssh -i ~/.ssh/rafi-key.pem ec2-user@18.119.109.47

# Update after pushing to GitHub
ssh -i ~/.ssh/rafi-key.pem ec2-user@18.119.109.47
cd ~/rafi/rafi_assistant && git pull && docker compose build && docker compose up -d

# Check health
curl https://rafi.intentionai.ai/health

# View logs
ssh -i ~/.ssh/rafi-key.pem ec2-user@18.119.109.47 \
  "cd ~/rafi/rafi_assistant && docker compose logs --tail 50 rafi"
```

**Key details:**
- Deploy key configured for `git pull` (no token needed)
- Secrets (`.env`, `config.yaml`) live on EC2 only, not in the repo
- systemd `rafi.service` auto-starts containers on EC2 reboot
- **Never run a local instance while EC2 is active** — duplicate Telegram polling causes 409 Conflicts

## Key Patterns

- **Config validation**: Pydantic models in `src/config/loader.py`. App refuses to start on invalid config.
- **Input sanitization**: All external text through `src/security/sanitizer.py` before LLM or DB.
- **LLM provider abstraction**: `LLMManager` orchestrates multiple providers with failover and cost-based routing.
- **Tool registration**: Tools gated by skill eligibility. `ToolRegistry.invoke()` handles dispatch.
- **Channel-agnostic processing**: `MessageProcessor` provides the same pipeline for all channels with ISC verification.
- **Memory promotion**: `MemoryPromotionJob` automatically promotes daily log insights to MEMORY.md.
- **Learning loop**: `LearningService` captures user feedback and derives behavioral adjustments.

## Security Requirements

- All Supabase queries use parameterized inputs
- Prompt injection detection on all user input
- Twilio webhook signature validation
- Telegram user_id authorization
- OAuth tokens encrypted with Fernet at rest
- API keys passed as env vars, never in Docker images

## Test Markers

Tests use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.security`, `@pytest.mark.e2e`.
