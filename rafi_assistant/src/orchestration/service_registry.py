from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List

logger = logging.getLogger(__name__)

@dataclass
class ServiceRegistry:
    """
    Centralized registry for all Rafi services.
    
    This registry acts as the orchestration hub for the assistant, allowing
    different components (FastAPI routes, Telegram bot, Desktop UI, LLM agents)
    to discover and interact with core services.
    
    It also provides an event-bus like mechanism via 'listeners' where components
    can subscribe to specific event types (voice, tools, ui, etc.).
    
    How to consume:
    1. UI: Subscribes to 'transcript' and 'voice' events to update symbols/text.
    2. LLM: Uses services registered here to execute tools.
    3. Voice: Emits 'transcript' events when speech is processed.
    """
    config: Any = None
    db: Any = None
    llm: Any = None
    calendar: Any = None
    email: Any = None
    tasks: Any = None
    notes: Any = None
    weather: Any = None
    memory: Any = None
    twilio: Any = None
    elevenlabs: Any = None
    deepgram: Any = None
    cad: Any = None
    browser: Any = None
    screen: Any = None
    
    # ADA-parity components
    conversation: Any = None
    vision: Any = None
    tools: Any = None
    
    # Event channels (queues) for streaming updates to UI/CLI
    transcript_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    tool_output_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    
    # Event listeners: event_type -> list of async callbacks
    _listeners: Dict[str, List[Callable[..., Coroutine[Any, Any, None]]]] = field(
        default_factory=lambda: {
            "voice": [],
            "tools": [],
            "ui": [],
            "transcript": [],
            "events": []
        }
    )

    def register_listener(self, event_type: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """
        Register an async callback for a specific event type.
        
        Args:
            event_type: The category of event (e.g., 'voice', 'transcript', 'ui').
            callback: An async function to be called when the event is emitted.
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)
        logger.debug(f"Registered listener for {event_type}")

    async def emit(self, event_type: str, *args: Any, **kwargs: Any) -> None:
        """
        Broadcast an event to all registered listeners of a given type.
        
        Args:
            event_type: The category of event.
            *args, **kwargs: Data associated with the event.
        """
        if event_type not in self._listeners:
            return
            
        callbacks = self._listeners[event_type]
        if not callbacks:
            return

        # Execute all listeners
        await asyncio.gather(
            *[callback(*args, **kwargs) for callback in callbacks],
            return_exceptions=True
        )

    async def broadcast_transcript(self, text: str, is_final: bool = True) -> None:
        """Add a transcript segment to the broadcast queue and notify listeners."""
        payload = {"text": text, "is_final": is_final}
        await self.transcript_queue.put(payload)
        await self.emit("transcript", **payload)

    async def broadcast_tool_result(self, tool_name: str, result: Any) -> None:
        """Add a tool execution result to the broadcast queue and notify listeners."""
        payload = {"tool": tool_name, "result": result}
        await self.tool_output_queue.put(payload)
        await self.emit("tools", **payload)

    async def broadcast_event(self, event_name: str, data: Any) -> None:
        """Add a generic event to the broadcast queue and notify listeners."""
        payload = {"event": event_name, "data": data}
        await self.event_queue.put(payload)
        await self.emit("events", **payload)
