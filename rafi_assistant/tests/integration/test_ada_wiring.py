import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.main import lifespan
from fastapi import FastAPI

@pytest.mark.asyncio
async def test_lifespan_initialization():
    """Test that the lifespan successfully initializes the ServiceRegistry and ADA components."""
    app = FastAPI()
    
    # Mock all external service initializations to avoid real API calls/DB connections
    with patch("src.main.load_config") as mock_load_config, \
         patch("src.main.SupabaseClient") as mock_db_class, \
         patch("src.main._create_llm_provider"), \
         patch("src.main.CalendarService") as mock_cal_class, \
         patch("src.main.EmailService"), \
         patch("src.main.TaskService"), \
         patch("src.main.NoteService"), \
         patch("src.main.WeatherService") as mock_weather_class, \
         patch("src.main.MemoryService"), \
         patch("src.main.DeepgramSTT"), \
         patch("src.main.TwilioHandler"), \
         patch("src.main.ElevenLabsAgent") as mock_el_class, \
         patch("src.main.RafiScheduler"), \
         patch("src.main.TelegramBot") as mock_bot_class, \
         patch("src.main.BriefingJob"), \
         patch("src.main.ReminderJob"):
        
        # Configure async mocks
        mock_db_class.return_value.initialize = AsyncMock()
        mock_cal_class.return_value.initialize = AsyncMock()
        mock_weather_class.return_value.initialize = AsyncMock()
        mock_el_class.return_value.create_agent = AsyncMock(return_value="agent-123")
        mock_bot_class.return_value.start = AsyncMock()
        
        async with lifespan(app):
            # Verify the registry was created and attached to app state
            assert hasattr(app.state, "registry")
            assert app.state.registry.conversation is not None
            assert app.state.registry.vision is not None
            assert app.state.registry.tools is not None
            
            # Verify some tools were registered
            tools = app.state.registry.tools.get_tool_definitions()
            assert any(t["name"] == "create_task" for t in tools)
