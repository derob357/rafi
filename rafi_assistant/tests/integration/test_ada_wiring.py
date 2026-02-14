from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from src.main import lifespan


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lifespan_initialization_current_wiring(mock_config):
    """Lifespan initializes registry/channel/scheduler wiring with current architecture."""
    app = FastAPI()

    with ExitStack() as stack:
        stack.enter_context(patch("src.main.load_config", return_value=mock_config))
        mock_db_class = stack.enter_context(patch("src.main.SupabaseClient"))
        mock_llm_factory = stack.enter_context(patch("src.main._create_llm_manager"))
        mock_calendar_class = stack.enter_context(patch("src.main.CalendarService"))
        mock_email_class = stack.enter_context(patch("src.main.EmailService"))
        stack.enter_context(patch("src.main.TaskService"))
        stack.enter_context(patch("src.main.NoteService"))
        mock_weather_class = stack.enter_context(patch("src.main.WeatherService"))
        stack.enter_context(patch("src.main.MemoryService"))
        stack.enter_context(patch("src.main.MemoryFileService"))
        stack.enter_context(patch("src.main.CadService"))
        mock_browser_class = stack.enter_context(patch("src.main.BrowserService"))
        stack.enter_context(patch("src.main.ScreenService"))
        stack.enter_context(patch("src.main.DeepgramSTT"))
        mock_twilio_class = stack.enter_context(patch("src.main.TwilioHandler"))
        mock_elevenlabs_class = stack.enter_context(patch("src.main.ElevenLabsAgent"))
        mock_registry_class = stack.enter_context(patch("src.main.ServiceRegistry"))
        stack.enter_context(patch("src.main.ConversationManager"))
        stack.enter_context(patch("src.main.CaptureDispatcher"))
        mock_tool_registry_class = stack.enter_context(patch("src.main.ToolRegistry"))
        mock_scheduler_class = stack.enter_context(patch("src.main.RafiScheduler"))
        mock_briefing_job_class = stack.enter_context(patch("src.main.BriefingJob"))
        mock_reminder_job_class = stack.enter_context(patch("src.main.ReminderJob"))
        stack.enter_context(patch("src.main.MessageProcessor"))
        stack.enter_context(patch("src.main.TelegramAdapter"))
        stack.enter_context(patch("src.main.WhatsAppAdapter"))
        mock_channel_manager_class = stack.enter_context(patch("src.main.ChannelManager"))
        stack.enter_context(patch("src.main.HeartbeatRunner"))

        db = mock_db_class.return_value
        db.initialize = AsyncMock()

        llm = MagicMock()
        llm.close = AsyncMock()
        mock_llm_factory.return_value = llm

        calendar = mock_calendar_class.return_value
        calendar.initialize = AsyncMock()
        calendar.sync_events_to_cache = AsyncMock(return_value=0)
        calendar._service = object()

        email = mock_email_class.return_value
        email.initialize = AsyncMock()
        email._service = object()

        weather = mock_weather_class.return_value
        weather.initialize = AsyncMock()
        weather.close = AsyncMock()

        browser = mock_browser_class.return_value
        browser.initialize = AsyncMock()
        browser.shutdown = AsyncMock()

        mock_twilio_class.return_value.set_agent_id = MagicMock()
        mock_elevenlabs_class.return_value.create_agent = AsyncMock(return_value="agent-test")

        registry = mock_registry_class.return_value
        registry.tools = mock_tool_registry_class.return_value
        registry.tools.register_tool = MagicMock()
        registry.tools.tool_names = ["create_task"]

        scheduler = mock_scheduler_class.return_value
        scheduler.set_briefing_callback = MagicMock()
        scheduler.set_reminder_callback = MagicMock()
        scheduler.set_calendar_sync_callback = MagicMock()
        scheduler.add_heartbeat = MagicMock()
        scheduler.setup_jobs = MagicMock()
        scheduler.start = MagicMock()
        scheduler.stop = MagicMock()

        mock_briefing_job_class.return_value.run = AsyncMock()
        mock_reminder_job_class.return_value.run = AsyncMock()

        channel_manager = mock_channel_manager_class.return_value
        channel_manager.register = MagicMock()
        channel_manager.start_all = AsyncMock()
        channel_manager.stop_all = AsyncMock()
        channel_manager.available_channels = ["telegram", "whatsapp"]

        async with lifespan(app):
            assert hasattr(app.state, "registry")
            assert app.state.registry is registry
            assert app.state.channel_manager is channel_manager
            assert app.state.calendar is calendar
            assert app.state.email is email

        channel_manager.start_all.assert_awaited_once()
        channel_manager.stop_all.assert_awaited_once()
        scheduler.start.assert_called_once()
        scheduler.stop.assert_called_once()
        browser.shutdown.assert_awaited_once()
        weather.close.assert_awaited_once()
        llm.close.assert_awaited_once()
