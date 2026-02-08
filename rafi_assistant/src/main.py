"""Rafi Assistant entry point.

Loads config, initializes all services, starts:
- FastAPI server for Twilio webhooks
- Telegram bot polling
- APScheduler for briefings, reminders, calendar sync
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, Response

from src.config.loader import load_config, AppConfig
from src.bot.telegram_bot import TelegramBot
from src.db.supabase_client import SupabaseClient
from src.llm.openai_provider import OpenAIProvider
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.provider import LLMProvider
from src.services.calendar_service import CalendarService
from src.services.email_service import EmailService
from src.services.task_service import TaskService
from src.services.note_service import NoteService
from src.services.weather_service import WeatherService
from src.services.memory_service import MemoryService
from src.voice.twilio_handler import TwilioHandler
from src.voice.elevenlabs_agent import ElevenLabsAgent
from src.voice.deepgram_stt import DeepgramSTT
from src.scheduling.scheduler import RafiScheduler
from src.scheduling.briefing_job import BriefingJob
from src.scheduling.reminder_job import ReminderJob

# Configure structured JSON logging
from pythonjsonlogger.json import JsonFormatter

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
_telegram_bot: TelegramBot | None = None
_scheduler: RafiScheduler | None = None


def _create_llm_provider(config: AppConfig) -> LLMProvider:
    """Create the appropriate LLM provider based on config."""
    provider = config.llm.provider.lower()
    if provider == "anthropic":
        return AnthropicProvider(config=config.llm)
    # Default to OpenAI
    return OpenAIProvider(config=config.llm)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    global _config, _telegram_bot, _scheduler

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

    # Initialize LLM provider
    llm = _create_llm_provider(_config)

    # Initialize services
    calendar_service = CalendarService(config=_config, db=db)
    await calendar_service.initialize()

    email_service = EmailService(config=_config, db=db)

    task_service = TaskService(db=db)
    note_service = NoteService(db=db)

    weather_service = WeatherService(config=_config.weather)
    await weather_service.initialize()

    memory_service = MemoryService(db=db, llm=llm)

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

    # Store services on app state for route access
    app.state.config = _config
    app.state.db = db
    app.state.llm = llm
    app.state.calendar = calendar_service
    app.state.email = email_service
    app.state.tasks = task_service
    app.state.notes = note_service
    app.state.weather = weather_service
    app.state.memory = memory_service
    app.state.twilio = twilio_handler
    app.state.elevenlabs = elevenlabs_agent
    app.state.deepgram = deepgram_stt

    # Create Telegram send helper for scheduler fallback
    async def send_telegram_message(text: str) -> None:
        if _telegram_bot:
            await _telegram_bot.send_message(text)

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

    _scheduler.set_briefing_callback(briefing_job.run)
    _scheduler.set_reminder_callback(reminder_job.run)
    _scheduler.set_calendar_sync_callback(calendar_service.sync_events_to_cache)
    _scheduler.setup_jobs()
    _scheduler.start()

    # Initialize and start Telegram bot
    _telegram_bot = TelegramBot(
        config=_config,
        db=db,
        llm=llm,
        memory=memory_service,
        calendar=calendar_service,
        email=email_service,
        tasks=task_service,
        notes=note_service,
        weather=weather_service,
        deepgram_stt=deepgram_stt,
    )

    # Start Telegram polling in background task
    bot_task = asyncio.create_task(_telegram_bot.start())
    logger.info("Rafi Assistant started for client: %s", _config.client.name)

    yield

    # Shutdown
    logger.info("Shutting down Rafi Assistant...")
    if _telegram_bot:
        await _telegram_bot.stop()
    if _scheduler:
        _scheduler.stop()
    await weather_service.close()
    await llm.close()
    bot_task.cancel()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Rafi Assistant",
    description="Personal AI Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)


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
