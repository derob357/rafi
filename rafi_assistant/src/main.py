"""Rafi Assistant entry point.

Loads config, initializes all services, starts:
- FastAPI server for Twilio webhooks
- Telegram bot polling
- APScheduler for briefings, reminders, calendar sync
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv

from fastapi import FastAPI, Request, Response

from src.config.loader import load_config, AppConfig
from src.channels.processor import MessageProcessor
from src.channels.telegram import TelegramAdapter
from src.channels.whatsapp import WhatsAppAdapter
from src.channels.manager import ChannelManager
from src.db.supabase_client import SupabaseClient
from src.llm.openai_provider import OpenAIProvider
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.groq_provider import GroqProvider
from src.llm.gemini_provider import GeminiProvider
from src.llm.provider import LLMProvider
from src.llm.llm_manager import LLMManager
from src.services.calendar_service import CalendarService
from src.services.email_service import EmailService
from src.services.task_service import TaskService
from src.services.note_service import NoteService
from src.services.weather_service import WeatherService
from src.services.memory_service import MemoryService
from src.services.memory_files import MemoryFileService
from src.services.cad_service import CadService
from src.services.browser_service import BrowserService
from src.services.screen_service import ScreenService
from src.voice.twilio_handler import TwilioHandler
from src.voice.elevenlabs_agent import ElevenLabsAgent
from src.voice.deepgram_stt import DeepgramSTT
from src.orchestration.service_registry import ServiceRegistry
from src.voice.conversation_manager import ConversationManager
from src.vision.capture import CaptureDispatcher
from src.tools.tool_registry import ToolRegistry
from src.llm.tool_definitions import TOOL_SCHEMA_MAP
from src.skills.loader import (
    build_startup_validation_report,
    discover_skills,
    filter_eligible,
    get_ineligibility_reasons,
    get_tool_names_for_skills,
)
from src.scheduling.scheduler import RafiScheduler
from src.scheduling.briefing_job import BriefingJob
from src.scheduling.reminder_job import ReminderJob
from src.scheduling.heartbeat import HeartbeatRunner
from src.scheduling.memory_promotion import MemoryPromotionJob
from src.services.isc_service import ISCService
from src.services.learning_service import LearningService

# Configure structured JSON logging
from pythonjsonlogger.json import JsonFormatter

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

log_handler = logging.StreamHandler(sys.stdout)
log_handler.setFormatter(
    JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        timestamp=True,
    )
)
logging.root.handlers = [log_handler]
logging.root.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Global service references
_config: AppConfig | None = None
_channel_manager: ChannelManager | None = None
_scheduler: RafiScheduler | None = None


def _create_llm_manager(config: AppConfig) -> LLMManager:
    """Create an LLM manager with all available providers."""
    llm_config = config.llm
    providers: dict[str, LLMProvider] = {}

    # OpenAI is always available (it's the default/required key)
    providers["openai"] = OpenAIProvider(config=llm_config)

    # Anthropic
    if llm_config.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(
            config=llm_config,
            api_key=llm_config.anthropic_api_key,
            openai_api_key=llm_config.api_key,
        )

    # Groq
    if llm_config.groq_api_key:
        providers["groq"] = GroqProvider(config=llm_config)

    # Gemini
    if llm_config.gemini_api_key:
        providers["gemini"] = GeminiProvider(config=llm_config)

    default = llm_config.provider if llm_config.provider in providers else "openai"

    logger.info("Available LLM providers: %s (default: %s)", list(providers.keys()), default)
    return LLMManager(providers=providers, default=default, embedding_provider=providers["openai"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    global _config, _channel_manager, _scheduler

    config_path = os.environ.get("RAFI_CONFIG_PATH", "/app/config.yaml")
    logger.info("Loading config from: %s", config_path)

    try:
        _config = load_config(config_path)
    except Exception as e:
        logger.critical("Failed to load config: %s", str(e))
        sys.exit(1)

    # Initialize database client
    db = SupabaseClient(config=_config.supabase)
    await db.initialize()

    # Initialize LLM providers
    llm = _create_llm_manager(_config)

    # Initialize services (Google services degrade gracefully without OAuth)
    calendar_service = CalendarService(config=_config, db=db)
    try:
        await calendar_service.initialize()
    except Exception as e:
        logger.warning("Calendar service unavailable: %s", e)

    email_service = EmailService(config=_config, db=db)
    try:
        await email_service.initialize()
    except Exception as e:
        logger.warning("Email service unavailable: %s", e)

    task_service = TaskService(db=db)
    note_service = NoteService(db=db)

    weather_service = WeatherService(config=_config.weather)
    try:
        await weather_service.initialize()
    except Exception as e:
        logger.warning("Weather service unavailable: %s", e)

    memory_service = MemoryService(db=db, llm=llm)
    memory_files = MemoryFileService()

    cad_service = CadService(db=db)
    
    browser_service = BrowserService(config=_config)
    try:
        await browser_service.initialize()
    except Exception as e:
        logger.warning("Browser service unavailable: %s", e)

    screen_service = ScreenService(registry=None)

    # Initialize Deepgram STT
    deepgram_stt = DeepgramSTT(api_key=_config.deepgram.api_key)

    # Initialize Twilio handler
    webhook_base_url = os.environ.get("WEBHOOK_BASE_URL", "")
    twilio_handler = TwilioHandler(
        account_sid=_config.twilio.account_sid,
        auth_token=_config.twilio.auth_token,
        phone_number=_config.twilio.phone_number,
        client_phone=_config.twilio.client_phone,
        webhook_base_url=webhook_base_url,
    )

    # Initialize ElevenLabs agent
    elevenlabs_agent = ElevenLabsAgent(
        api_key=_config.elevenlabs.api_key,
        voice_id=_config.elevenlabs.voice_id,
        agent_name=_config.elevenlabs.agent_name,
        personality=_config.elevenlabs.personality,
        llm_model=_config.llm.model,
    )

    # Create ElevenLabs agent and connect to Twilio
    try:
        agent_id = await elevenlabs_agent.create_agent(
            webhook_url=webhook_base_url,
        )
        twilio_handler.set_agent_id(agent_id)
        logger.info("ElevenLabs agent ready: %s", agent_id)
    except Exception as e:
        logger.error("Failed to create ElevenLabs agent: %s", str(e))
        logger.warning("Voice calls will not be available")

    # Initialize Service Registry
    registry = ServiceRegistry(
        config=_config,
        db=db,
        llm=llm,
        calendar=calendar_service,
        email=email_service,
        tasks=task_service,
        notes=note_service,
        weather=weather_service,
        memory=memory_service,
        twilio=twilio_handler,
        elevenlabs=elevenlabs_agent,
        deepgram=deepgram_stt,
        cad=cad_service,
        browser=browser_service,
        screen=screen_service
    )

    # Initialize ADA-parity managers
    registry.conversation = ConversationManager(registry)
    registry.vision = CaptureDispatcher(registry)
    registry.tools = ToolRegistry(registry)

    # -- Tool wrapper functions ------------------------------------------------
    # Each wrapper calls the underlying service, formats the result as a
    # human-readable string, and is registered with its OpenAI schema so the
    # ToolRegistry becomes the single source of truth for tool execution.
    # Runtime skill-gating pipeline
    discovered_skills = discover_skills()
    eligible_skills = filter_eligible(discovered_skills)
    ineligibility_reasons = get_ineligibility_reasons(discovered_skills)
    eligible_tool_names = get_tool_names_for_skills(eligible_skills)
    eligible_schema_map = {
        name: schema
        for name, schema in TOOL_SCHEMA_MAP.items()
        if name in eligible_tool_names
    }

    discovered_skill_names = sorted(skill.name for skill in discovered_skills)
    eligible_skill_names = sorted(skill.name for skill in eligible_skills)

    logger.info(
        "Skills discovered (%d): %s",
        len(discovered_skill_names),
        discovered_skill_names,
    )
    logger.info(
        "Skills eligible (%d): %s",
        len(eligible_skill_names),
        eligible_skill_names,
    )
    for skill_name, reasons in sorted(ineligibility_reasons.items()):
        if reasons.get("disabled"):
            logger.info("Skill ineligible: %s (disabled)", skill_name)
        missing_env = reasons.get("missing_env", [])
        if missing_env:
            logger.info(
                "Skill ineligible: %s (missing env vars: %s)",
                skill_name,
                missing_env,
            )

    # Calendar
    async def _read_calendar(days: int = 7) -> str:
        events = await calendar_service.list_events(days=days)
        if not events:
            return "No upcoming events found."
        lines = []
        for e in events:
            line = (
                f"- {e.get('summary', 'Untitled')} | "
                f"{e.get('start', '')} to {e.get('end', '')}"
            )
            if e.get("location"):
                line += f" @ {e['location']}"
            lines.append(line)
        return "\n".join(lines)

    async def _create_event(
        summary: str, start: str, end: str, location: str | None = None,
    ) -> str:
        result = await calendar_service.create_event(
            summary=summary, start=start, end=end, location=location,
        )
        if result:
            return f"Event created: {result.get('summary', '')} (ID: {result.get('id', '')})"
        return "Failed to create event."

    async def _update_event(event_id: str, **kwargs: Any) -> str:
        result = await calendar_service.update_event(event_id, kwargs)
        if result:
            return f"Event updated: {result.get('summary', '')}"
        return "Failed to update event."

    async def _delete_event(event_id: str) -> str:
        success = await calendar_service.delete_event(event_id)
        return "Event deleted." if success else "Failed to delete event."

    async def _get_google_auth_url() -> str:
        url = await calendar_service.get_auth_url()
        if url:
            return f"Please visit this URL to authorize Google access:\n{url}"
        return "Failed to generate authorization URL."

    # Email
    async def _read_emails(count: int = 20, unread_only: bool = False) -> str:
        emails = await email_service.list_emails(count=count, unread_only=unread_only)
        if not emails:
            return "No emails found."
        lines = []
        for em in emails[:10]:
            lines.append(
                f"- From: {em.get('from', 'Unknown')} | "
                f"Subject: {em.get('subject', 'No subject')} | "
                f"Date: {em.get('date', '')}"
            )
        return "\n".join(lines)

    async def _search_emails(query: str) -> str:
        emails = await email_service.search_emails(query)
        if not emails:
            return "No emails matched your search."
        lines = []
        for em in emails[:10]:
            lines.append(
                f"- From: {em.get('from', 'Unknown')} | "
                f"Subject: {em.get('subject', 'No subject')} | "
                f"Snippet: {em.get('snippet', '')[:100]}"
            )
        return "\n".join(lines)

    async def _send_email(to: str, subject: str, body: str) -> str:
        result = await email_service.send_email(to=to, subject=subject, body=body)
        if result:
            return f"Email sent to {to}."
        return "Failed to send email."

    # Tasks
    async def _create_task(
        title: str, description: str | None = None, due_date: str | None = None,
    ) -> str:
        result = await task_service.create_task(
            title=title, description=description, due_date=due_date,
        )
        if result:
            return f"Task created: {result.get('title', '')} (ID: {result.get('id', '')})"
        return "Failed to create task."

    async def _list_tasks(status: str | None = None) -> str:
        tasks = await task_service.list_tasks(status=status)
        if not tasks:
            return "No tasks found."
        lines = []
        for t in tasks:
            due = f" (due: {t['due_date']})" if t.get("due_date") else ""
            lines.append(
                f"- [{t.get('status', 'pending')}] {t.get('title', 'Untitled')}{due}"
            )
        return "\n".join(lines)

    async def _update_task(task_id: str, **kwargs: Any) -> str:
        result = await task_service.update_task(task_id, kwargs)
        if result:
            return f"Task updated: {result.get('title', '')}"
        return "Failed to update task."

    async def _delete_task(task_id: str) -> str:
        success = await task_service.delete_task(task_id)
        return "Task deleted." if success else "Failed to delete task."

    async def _complete_task(task_id: str) -> str:
        result = await task_service.complete_task(task_id)
        if result:
            return f"Task completed: {result.get('title', '')}"
        return "Failed to complete task."

    # Notes
    async def _create_note(title: str, content: str) -> str:
        result = await note_service.create_note(title=title, content=content)
        if result:
            return f"Note created: {result.get('title', '')} (ID: {result.get('id', '')})"
        return "Failed to create note."

    async def _list_notes() -> str:
        notes = await note_service.list_notes()
        if not notes:
            return "No notes found."
        lines = []
        for n in notes:
            lines.append(f"- {n.get('title', 'Untitled')} (ID: {n.get('id', '')})")
        return "\n".join(lines)

    async def _get_note(note_id: str) -> str:
        note = await note_service.get_note(note_id)
        if note:
            return f"Title: {note.get('title', '')}\n\n{note.get('content', '')}"
        return "Note not found."

    async def _update_note(note_id: str, **kwargs: Any) -> str:
        result = await note_service.update_note(note_id, kwargs)
        if result:
            return f"Note updated: {result.get('title', '')}"
        return "Failed to update note."

    async def _delete_note(note_id: str) -> str:
        success = await note_service.delete_note(note_id)
        return "Note deleted." if success else "Failed to delete note."

    # Weather
    async def _get_weather(location: str | None = None) -> str:
        if location:
            return await weather_service.get_weather(location)
        next_event = await calendar_service.get_next_event()
        return await weather_service.get_weather_for_event(next_event)

    # Memory
    async def _recall_memory(query: str, limit: int = 5) -> str:
        results = await memory_service.search_memory(query=query, limit=limit)
        if not results:
            return "I don't have any relevant memories about that."
        lines = []
        for r in results:
            lines.append(
                f"[{r.get('role', 'unknown')}] {r.get('content', '')[:200]}"
            )
        return "\n".join(lines)

    # Settings
    async def _update_setting(key: str, value: str) -> str:
        allowed = {
            "morning_briefing_time", "quiet_hours_start", "quiet_hours_end",
            "reminder_lead_minutes", "min_snooze_minutes",
        }
        if key not in allowed:
            return f"Unknown setting: {key}. Allowed: {', '.join(sorted(allowed))}"
        current = getattr(_config.settings, key, None)
        try:
            if key in ("reminder_lead_minutes", "min_snooze_minutes"):
                setattr(_config.settings, key, int(value))
            else:
                setattr(_config.settings, key, value)
        except Exception as e:
            return f"Error updating setting: {e}"
        return f"Setting '{key}' updated from '{current}' to '{value}'."

    async def _get_settings() -> str:
        settings = _config.settings.model_dump() if _config else {}
        if not settings:
            return "No custom settings found."
        lines = []
        for k, v in settings.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    # -- Register all tools with schemas for LLM function calling ------------
    tool_reg = registry.tools

    def _register_if_enabled(name: str, func: Any, description: str) -> None:
        if name not in eligible_tool_names:
            logger.debug("Tool gated by skills: %s", name)
            return
        if name not in eligible_schema_map:
            logger.warning("Eligible tool missing schema: %s", name)
        tool_reg.register_tool(name, func, description, schema=eligible_schema_map.get(name))

    # Calendar
    _register_if_enabled("read_calendar", _read_calendar, "List upcoming calendar events")
    _register_if_enabled("create_event", _create_event, "Create a calendar event")
    _register_if_enabled("update_event", _update_event, "Update a calendar event")
    _register_if_enabled("delete_event", _delete_event, "Delete a calendar event")
    _register_if_enabled("get_google_auth_url", _get_google_auth_url, "Get Google OAuth URL")

    # Email
    _register_if_enabled("read_emails", _read_emails, "Read recent emails")
    _register_if_enabled("search_emails", _search_emails, "Search emails")
    _register_if_enabled("send_email", _send_email, "Send an email")

    # Tasks
    _register_if_enabled("create_task", _create_task, "Create a task")
    _register_if_enabled("list_tasks", _list_tasks, "List tasks")
    _register_if_enabled("update_task", _update_task, "Update a task")
    _register_if_enabled("delete_task", _delete_task, "Delete a task")
    _register_if_enabled("complete_task", _complete_task, "Complete a task")

    # Notes
    _register_if_enabled("create_note", _create_note, "Create a note")
    _register_if_enabled("list_notes", _list_notes, "List notes")
    _register_if_enabled("get_note", _get_note, "Get a note")
    _register_if_enabled("update_note", _update_note, "Update a note")
    _register_if_enabled("delete_note", _delete_note, "Delete a note")

    # Weather
    _register_if_enabled("get_weather", _get_weather, "Get weather")

    # Memory
    _register_if_enabled("recall_memory", _recall_memory, "Search conversation history")

    # Settings
    _register_if_enabled("update_setting", _update_setting, "Update a setting")
    _register_if_enabled("get_settings", _get_settings, "Get current settings")

    # CAD, Browser, Screen (return dicts/strings, auto-serialized by invoke())
    _register_if_enabled("generate_cad", cad_service.generate_stl, "Generate a 3D CAD model")
    _register_if_enabled("browse_web", browser_service.browse, "Navigate to a website")
    _register_if_enabled("search_web", browser_service.search, "Search the web")
    _register_if_enabled("mouse_move", screen_service.move_mouse, "Move mouse")
    _register_if_enabled("mouse_click", screen_service.click, "Click mouse")
    _register_if_enabled("keyboard_type", screen_service.type_text, "Type text")

    enabled_tool_names = sorted(tool_reg.tool_names)
    logger.info(
        "Enabled tools after skill gating (%d): %s",
        len(enabled_tool_names),
        enabled_tool_names,
    )
    logger.info(
        "\n%s",
        build_startup_validation_report(
            discovered_skills=discovered_skills,
            eligible_skills=eligible_skills,
            ineligibility_reasons=ineligibility_reasons,
            exposed_tools=enabled_tool_names,
        ),
    )

    # Store registry on app state for route access
    app.state.registry = registry
    app.state.register_listener = registry.register_listener
    app.state.emit_event = registry.emit

    # For backward compatibility with existing routes
    app.state.config = _config
    app.state.db = db
    app.state.llm = llm
    app.state.llm_manager = llm
    app.state.calendar = calendar_service
    app.state.email = email_service
    app.state.tasks = task_service
    app.state.notes = note_service
    app.state.weather = weather_service
    app.state.memory = memory_service
    app.state.memory_files = memory_files
    app.state.twilio = twilio_handler
    app.state.elevenlabs = elevenlabs_agent
    app.state.deepgram = deepgram_stt
    app.state.cad = cad_service
    app.state.browser = browser_service

    # Create Telegram send helper for scheduler fallback
    async def send_telegram_message(text: str) -> None:
        if _channel_manager:
            await _channel_manager.send_to_preferred(text)

    # Initialize scheduler
    _scheduler = RafiScheduler(_config)

    briefing_job = BriefingJob(
        calendar_service=calendar_service,
        email_service=email_service,
        task_service=task_service,
        weather_service=weather_service,
        twilio_handler=twilio_handler,
        telegram_send_func=send_telegram_message,
        quiet_hours_start=_config.settings.quiet_hours_start,
        quiet_hours_end=_config.settings.quiet_hours_end,
        timezone=_config.settings.timezone,
    )

    reminder_job = ReminderJob(
        supabase_client=db,
        twilio_handler=twilio_handler,
        telegram_send_func=send_telegram_message,
        reminder_lead_minutes=_config.settings.reminder_lead_minutes,
        min_snooze_minutes=_config.settings.min_snooze_minutes,
        quiet_hours_start=_config.settings.quiet_hours_start,
        quiet_hours_end=_config.settings.quiet_hours_end,
        timezone=_config.settings.timezone,
    )

    # -- ISC and Learning services --------------------------------------------
    isc_service = ISCService(llm=llm)
    learning_service = LearningService(db=db, llm=llm, memory_files=memory_files)

    # -- Channel system -------------------------------------------------------
    # Shared message processor (LLM orchestration for all channels)
    processor = MessageProcessor(
        config=_config,
        llm=llm,
        memory=memory_service,
        tool_registry=registry.tools,
        memory_files=memory_files,
        isc_service=isc_service,
        learning_service=learning_service,
    )

    # Channel adapters
    telegram_adapter = TelegramAdapter(
        config=_config,
        db=db,
        processor=processor,
        deepgram_stt=deepgram_stt,
        llm_manager=llm,
    )

    whatsapp_adapter = WhatsAppAdapter(
        config=_config,
        processor=processor,
    )

    _channel_manager = ChannelManager(preferred_channel="telegram")
    _channel_manager.register(telegram_adapter)
    _channel_manager.register(whatsapp_adapter)

    app.state.channel_manager = _channel_manager
    app.state.whatsapp_adapter = whatsapp_adapter

    # -- Heartbeat runner -----------------------------------------------------
    heartbeat = HeartbeatRunner(
        config=_config,
        llm=llm,
        memory_files=memory_files,
        channel_manager=_channel_manager,
        calendar=calendar_service,
        email=email_service,
        tasks=task_service,
        weather=weather_service,
    )

    # -- Memory promotion job (daily at 23:00) --------------------------------
    memory_promotion = MemoryPromotionJob(llm=llm, memory_files=memory_files)

    # -- Learning analysis callback -------------------------------------------
    async def _run_learning_analysis() -> None:
        """Periodic analysis of feedback to generate behavioral adjustments."""
        adjustments = await learning_service.generate_adjustments()
        if adjustments:
            await learning_service.apply_adjustments_to_memory(adjustments)

    # Register all scheduler callbacks and start
    _scheduler.set_briefing_callback(briefing_job.run)
    _scheduler.set_reminder_callback(reminder_job.run)
    _scheduler.set_calendar_sync_callback(calendar_service.sync_events_to_cache)
    _scheduler.add_heartbeat(heartbeat.run)
    _scheduler.add_daily_job("memory_promotion", memory_promotion.run, hour=23, minute=0)
    _scheduler.add_daily_job("learning_analysis", _run_learning_analysis, hour=23, minute=30)
    _scheduler.setup_jobs()
    _scheduler.start()

    logger.info("--- Rafi Assistant Services Status ---")
    logger.info("Database: ONLINE")
    logger.info("STT (Deepgram): ONLINE")
    logger.info("TTS (ElevenLabs): ONLINE")
    logger.info("Calendar: %s", "ONLINE" if calendar_service._service else "OFFLINE")
    logger.info("Email: %s", "ONLINE" if email_service._service else "OFFLINE")
    logger.info("Browser: ONLINE")
    logger.info("Weather: ONLINE")
    logger.info("Channels: %s", _channel_manager.available_channels)
    logger.info("Heartbeat: every 30 minutes")
    logger.info("---------------------------------------")
    logger.info("Rafi Assistant logic initialized successfully.")

    # Start channels (Telegram polling, WhatsApp client init)
    await _channel_manager.start_all()
    logger.info("Rafi Assistant started for client: %s", _config.client.name)

    yield

    # Shutdown
    logger.info("Shutting down Rafi Assistant...")
    await browser_service.shutdown()
    if _channel_manager:
        await _channel_manager.stop_all()
    if _scheduler:
        _scheduler.stop()
    await weather_service.close()
    await llm.close()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Rafi Assistant",
    description="Personal AI Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)


# Root endpoint
@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with basic service info."""
    return {"service": "rafi_assistant", "status": "running"}


# Health check endpoint
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "service": "rafi_assistant"}


# Twilio webhook routes
@app.post("/api/twilio/voice")
async def twilio_voice(request: Request) -> Response:
    """Handle inbound Twilio voice calls."""
    twilio_handler: TwilioHandler = request.app.state.twilio
    return await twilio_handler.handle_inbound_call(request)


@app.post("/api/twilio/status")
async def twilio_status(request: Request) -> Response:
    """Handle Twilio call status callbacks."""
    twilio_handler: TwilioHandler = request.app.state.twilio
    return await twilio_handler.handle_call_status(request)


@app.post("/api/tools/{tool_name}")
async def handle_tool_call(tool_name: str, request: Request) -> Response:
    """Handle tool call webhooks from ElevenLabs during voice conversations."""
    twilio_handler: TwilioHandler = request.app.state.twilio
    return await twilio_handler.handle_tool_call(request)


# WhatsApp webhook route (Twilio WhatsApp messages)
@app.post("/api/whatsapp/inbound")
async def whatsapp_inbound(request: Request) -> Response:
    """Handle inbound WhatsApp messages from Twilio."""
    from src.channels.whatsapp import WhatsAppAdapter

    adapter: WhatsAppAdapter = request.app.state.whatsapp_adapter
    form_data = await request.form()
    twiml = await adapter.handle_inbound(dict(form_data))

    return Response(content=twiml, media_type="application/xml")


# -- Dashboard endpoint (Phase 4) ------------------------------------------

@app.get("/api/dashboard")
async def dashboard(request: Request) -> dict[str, Any]:
    """Observability dashboard data endpoint.

    Returns current system state including active services, recent feedback,
    memory stats, and scheduler status.
    """
    registry: ServiceRegistry = request.app.state.registry
    memory_files: MemoryFileService = request.app.state.memory_files
    channel_manager: ChannelManager = request.app.state.channel_manager

    # Gather dashboard data
    daily_logs = memory_files.list_daily_logs(limit=3)
    log_stats = [
        {"date": date_str, "exchanges": content.count("**User**") + content.count("**Rafi**")}
        for date_str, content in daily_logs
    ]

    return {
        "status": "running",
        "services": {
            "database": "online",
            "llm_provider": registry.llm.active_name if hasattr(registry.llm, "active_name") else "unknown",
            "llm_available": registry.llm.available if hasattr(registry.llm, "available") else [],
            "channels": channel_manager.available_channels if channel_manager else [],
            "heartbeat": "active",
        },
        "memory": {
            "soul": bool(memory_files.load_soul()),
            "user": bool(memory_files.load_user()),
            "long_term": bool(memory_files.load_memory()),
            "agents": bool(memory_files.load_agents()),
            "heartbeat": not memory_files.is_heartbeat_empty(),
        },
        "daily_logs": log_stats,
        "tools": registry.tools.tool_names if registry.tools else [],
    }


@app.get("/api/dashboard/feedback")
async def dashboard_feedback(request: Request) -> dict[str, Any]:
    """Get recent feedback signals for the dashboard."""
    db: SupabaseClient = request.app.state.db
    llm = request.app.state.llm
    memory_files: MemoryFileService = request.app.state.memory_files

    learning = LearningService(db=db, llm=llm, memory_files=memory_files)
    feedback = await learning.get_recent_feedback(days=7, limit=20)

    return {
        "count": len(feedback),
        "signals": feedback,
    }


# OAuth callback route
@app.get("/oauth/callback")
async def oauth_callback(request: Request) -> dict[str, str]:
    """Handle Google OAuth callback to store tokens."""
    code = request.query_params.get("code")
    if not code:
        return {"error": "Missing authorization code"}

    try:
        from google_auth_oauthlib.flow import Flow

        config: AppConfig = request.app.state.config
        db: SupabaseClient = request.app.state.db

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": config.google.client_id,
                    "client_secret": config.google.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
            redirect_uri=str(request.url_for("oauth_callback")),
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Encrypt and store tokens
        from cryptography.fernet import Fernet

        encryption_key = os.environ.get("OAUTH_ENCRYPTION_KEY", "")
        if encryption_key:
            fernet = Fernet(encryption_key.encode())
            encrypted_access = fernet.encrypt(
                credentials.token.encode()
            ).decode()
            encrypted_refresh = fernet.encrypt(
                credentials.refresh_token.encode()
            ).decode()
        else:
            logger.warning("No OAUTH_ENCRYPTION_KEY set, storing tokens unencrypted")
            encrypted_access = credentials.token
            encrypted_refresh = credentials.refresh_token

        await db.upsert(
            "oauth_tokens",
            data={
                "provider": "google",
                "access_token": encrypted_access,
                "refresh_token": encrypted_refresh,
                "expires_at": credentials.expiry.isoformat() if credentials.expiry else None,
                "scopes": " ".join(credentials.scopes or []),
            },
            on_conflict="provider",
        )

        logger.info("Google OAuth tokens stored successfully")
        return {"status": "success", "message": "Google account connected!"}

    except Exception as e:
        logger.exception("OAuth callback failed: %s", str(e))
        return {"error": "Failed to complete authorization"}
