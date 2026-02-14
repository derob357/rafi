# Rafi Assistant Test Plan

## 1) Objectives

- Prevent regressions in the core assistant loop: inbound message -> safety checks -> context -> LLM/tool calls -> response.
- Catch integration breakages early for Google, Supabase, Twilio, Deepgram, ElevenLabs, and Weather providers.
- Make startup and skill-gating behavior deterministic and testable.
- Separate fast deterministic tests from credential-dependent smoke tests.

## 2) Current State Summary

### Strengths

- Strong unit coverage for services (`calendar`, `email`, `tasks`, `notes`, `memory`), `tool_registry`, sanitizer, validators, config loader, and LLM providers.
- Marker strategy is already defined in `pytest.ini` (`unit`, `integration`, `security`, `e2e`).
- Good fixture base in `tests/conftest.py` for config and mocked external clients.

### Gaps and Risks

- Minimal direct tests for startup and channel orchestration (`src/main.py`, `src/channels/processor.py`, `src/channels/manager.py`).
- No dedicated tests yet for skill loader + startup validation report + schema/tool gating.
- Scheduler/heartbeat paths are mostly untested.
- Some integration/e2e files are smoke placeholders and do not assert deep business invariants.
- `tests/integration/test_ada_wiring.py` references stale symbols and should be rewritten.

## 3) Risk-Based Method Analysis

### Tier 0 (must cover first)

#### Startup and Tool Exposure

- `src/main.py`
  - `lifespan(...)`
  - nested `_register_if_enabled(...)`
  - skill discovery/eligibility + schema filtering flow
- `src/skills/loader.py`
  - `parse_skill_file(...)`
  - `discover_skills(...)`
  - `filter_eligible(...)`
  - `get_ineligibility_reasons(...)`
  - `get_tool_names_for_skills(...)`
  - `build_startup_validation_report(...)`

Why: this controls which tools the model can call and which integrations are visible.

#### Core Message Orchestration

- `src/channels/processor.py`
  - `_build_system_prompt(...)`
  - `process(...)`

Why: this is the main behavior path for every channel.

#### Tool Dispatch Safety

- `src/tools/tool_registry.py`
  - `invoke(...)`
  - `get_openai_schemas(...)`

Why: this is the execution boundary between LLM output and side effects.

### Tier 1 (high)

#### Channel Routing and Proactive Notifications

- `src/channels/manager.py`
  - `start_all(...)`, `stop_all(...)`
  - `send_to_preferred(...)`
  - `send_to_channel(...)`

#### Scheduler and Heartbeat

- `src/scheduling/scheduler.py`
  - `_parse_time(...)`
  - `_setup_*_job(...)`
  - `update_briefing_time(...)`
- `src/scheduling/heartbeat.py`
  - `_is_quiet_hours(...)`
  - `_gather_context(...)`
  - `_build_prompt(...)`
  - `run(...)`

Why: drives proactive behavior, dedup, and alert quality.

### Tier 2 (medium)

- `src/services/calendar_service.py`: token refresh branches, retry behavior, cache sync.
- `src/services/email_service.py`: body extraction variants, send path, unread count path.
- `src/services/weather_service.py`: API formatting and graceful fallback.
- `src/services/task_service.py` and `src/services/note_service.py`: validation and CRUD edge cases.
- `src/services/memory_service.py`: embedding fallback and hybrid search fallback order.
- Voice stack:
  - `src/voice/twilio_handler.py`
  - `src/voice/deepgram_stt.py`
  - `src/voice/elevenlabs_agent.py`

## 4) Test Matrix (What to Add)

### 4.1 Unit Tests (fast and deterministic)

#### A) Startup and Skill Gating

Add `tests/unit/test_skill_loader.py`:

- `parse_skill_file`: valid parse, missing frontmatter, invalid YAML, missing `name`.
- `discover_skills`: finds valid skill dirs and ignores malformed ones.
- `get_ineligibility_reasons`: disabled skills and missing env vars.
- `filter_eligible`: returns only eligible skills.
- `get_tool_names_for_skills`: deduplicates names.
- `build_startup_validation_report`: includes expected counts and sections.

Add `tests/unit/test_main_skill_gating.py`:

- Only eligible tools are registered when env vars are missing.
- Exposed tool schemas match registered tools.
- Startup report/log lines include missing env keys.

#### B) Message Processor Orchestration

Add `tests/unit/test_message_processor.py`:

- Empty sanitized input returns fallback text.
- Prompt injection returns rejection and does not call `llm.chat`.
- Non-tool happy path stores user and assistant messages.
- Tool-call path executes tool and loops correctly.
- Invalid tool JSON arguments gracefully fallback to `{}`.
- LLM exception returns retry-friendly message.
- Max tool rounds exhausted path returns final fallback.
- Prompt build source:
  - with `MemoryFileService`
  - without `MemoryFileService`

#### C) Channel Manager Behavior

Add `tests/unit/test_channel_manager.py`:

- `start_all` skips unconfigured adapters.
- `start_all` isolates adapter exceptions.
- `send_to_preferred` preferred success path.
- `send_to_preferred` fallback path.
- `send_to_preferred` no channel available path.
- `send_to_channel` unknown channel path.

#### D) Scheduler and Heartbeat

Add `tests/unit/test_scheduler.py`:

- `_parse_time` valid and invalid values.
- setup methods skip when callbacks are absent.
- setup methods add jobs when callbacks are present.
- `update_briefing_time` reschedules existing jobs only.

Add `tests/unit/test_heartbeat.py`:

- quiet-hour logic for same-day and overnight windows.
- `run` skips when checklist empty.
- `run` skips during quiet hours.
- alert path sends notification.
- dedup suppresses duplicate within 24h.
- `HEARTBEAT_OK` path sends nothing.
- `_gather_context` tolerates partial service failures.

#### E) Voice Stack Methods

Add `tests/unit/test_twilio_handler.py`:

- Invalid signature returns 403.
- Inbound with no agent ID returns apology TwiML.
- Inbound with agent ID includes conversation relay.
- Outbound success returns SID.
- Outbound exception returns `None`.

Add `tests/unit/test_deepgram_stt.py`:

- Missing/nonexistent/empty audio path returns `None`.
- Success path returns sanitized transcript.
- Retries on `HTTPStatusError` and `RequestError`.
- `_extract_transcript` handles malformed payloads.

Add `tests/unit/test_elevenlabs_agent.py`:

- Constructor validation (`api_key`, `voice_id`).
- `create_agent` success sets `agent_id`.
- `create_agent` missing `agent_id` raises.
- `get_signed_url` without `agent_id` returns `None`.
- `extract_transcript_text` handles empty/mixed transcript entries.

### 4.2 Integration Tests (credential-aware)

Refactor integration tests into explicit contracts with deterministic skips.

Required contracts:

- Google Calendar: list events sanity, optional create+cleanup in nightly.
- Gmail: list/search sanity, send only in sandbox mailbox mode.
- Supabase: CRUD against isolated test data.
- Weather: known location parseable response.
- Twilio/Deepgram/ElevenLabs: smoke-only unless sandbox is stable.

Rules:

- Live integration tests must be idempotent and cleanup their artifacts.
- Use unique run IDs/prefixes for data isolation.

### 4.3 E2E Tests

Split E2E into two tracks:

- Contract E2E (CI-safe): mocked external APIs, full internal orchestration assertions.
- Live E2E (nightly/manual): real credentials and webhooks.

Contract E2E targets:

- Telegram text -> MessageProcessor -> tool call -> response persisted.
- Voice transcript path -> sanitize -> process -> response.
- Heartbeat tick with actionable context sends exactly one proactive notification.

Live E2E targets:

- Twilio voice webhook to transcript summary path.
- Startup with Google connected exposes calendar/email tools.
- Startup with missing env hides gated tools and logs report correctly.

### 4.4 Security Tests

Expand method-level security coverage:

- `src/security/sanitizer.py`: fuzz for mixed Unicode/control chars.
- `src/security/auth.py`: Twilio signature edge cases.
- `src/channels/processor.py`: injection detection blocks `llm.chat`.
- `src/tools/tool_registry.py`: unknown tool names cannot execute side effects.

## 5) Fixtures, Mocks, and Data Strategy

### 5.1 Keep in `tests/conftest.py`

- `mock_config`, `mock_supabase`, `mock_openai`, `mock_twilio`.

### 5.2 Add Fixtures

- `skill_dir_factory(tmp_path)` for synthetic skill trees.
- `fake_channel_adapter` with configurable behaviors.
- `mock_llm_chat_sequence` for scripted multi-round tool calls.
- Time-freeze fixture for heartbeat dedup and quiet-hours tests.

### 5.3 Mocking Rules

- Patch at module boundaries (service constructors, adapters), not deep internals.
- Prefer strict mocks (`spec_set=True`) for external clients to detect API drift.

### 5.4 Environment Sets

- `.env.test` separate from local `.env`.
- Suggested flags:
  - `UNIT_ONLY=1`
  - `INTEGRATION_GOOGLE=1`
  - `INTEGRATION_VOICE=1`
  - `RAFI_E2E_TEST=1`

## 6) CI Pipeline and Quality Gates

### Stage 1 (every PR)

- `pytest -m unit`
- `pytest -m security`
- Target runtime: under 4 minutes.

### Stage 2 (protected branches)

- `pytest -m "unit or security" --cov=src --cov-report=term-missing`
- Coverage gates:
  - Global line coverage >= 80%
  - Critical files >= 90%:
    - `src/channels/processor.py`
    - `src/skills/loader.py`
    - `src/tools/tool_registry.py`
    - `src/scheduling/heartbeat.py`

### Stage 3 (nightly)

- `pytest -m integration`
- `pytest -m e2e` (live subset)
- Publish per-provider results and flaky-test summary.

## 7) Rollout Roadmap

### Sprint 1 (P0)

- Add tests for `skills/loader.py`, startup gating in `main.py`, and `MessageProcessor`.
- Rewrite `tests/integration/test_ada_wiring.py` against current architecture.

### Sprint 2 (P1)

- Add `ChannelManager`, scheduler, and heartbeat test suites.
- Add voice unit suites (`twilio_handler`, `deepgram_stt`, `elevenlabs_agent`).

### Sprint 3 (P1/P2)

- Upgrade integration contracts.
- Split E2E into contract vs live.
- Enforce coverage thresholds in CI.

## 8) Definition of Done

- Tier 0 and Tier 1 methods have deterministic unit tests with explicit assertions.
- Startup skill/tool gating has tests for both eligible and missing-env conditions.
- Heartbeat dedup and quiet-hour behavior are fully covered.
- PR CI enforces unit/security and coverage thresholds.
- Nightly pipelines run integration/live E2E with clear credential gates.

## 9) Immediate File Backlog

1. `tests/unit/test_skill_loader.py`
2. `tests/unit/test_main_skill_gating.py`
3. `tests/unit/test_message_processor.py`
4. `tests/unit/test_channel_manager.py`
5. `tests/unit/test_scheduler.py`
6. `tests/unit/test_heartbeat.py`
7. `tests/unit/test_twilio_handler.py`
8. `tests/unit/test_deepgram_stt.py`
9. `tests/unit/test_elevenlabs_agent.py`
10. rewrite `tests/integration/test_ada_wiring.py`
