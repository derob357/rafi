import asyncio
import logging

logger = logging.getLogger(__name__)

class ConversationManager:
    """
    Orchestrates the voice interaction flow.

    Binds Deepgram (STT) and ElevenLabs (TTS/Agent) together,
    managing the listening state and broadcasting transcripts to the registry.
    """
    def __init__(self, registry):
        self.registry = registry
        self.stt = registry.deepgram
        self.tts = registry.elevenlabs
        self._is_listening = False
        self._is_speaking = False

    async def start_listening(self):
        """Start the microphone listener and stream to Deepgram."""
        if self._is_listening:
            return

        self._is_listening = True
        logger.info("ConversationManager: Started listening")
        await self.registry.emit("voice", status="listening")

        # Real microphone → Deepgram STT pipeline not yet wired.
        # When implemented, this will start a VAD loop + audio stream.
        logger.info("ConversationManager: Mic active (STT pipeline not yet connected)")

    async def stop_listening(self):
        """Stop the microphone listener."""
        self._is_listening = False
        logger.info("ConversationManager: Stopped listening")
        await self.registry.emit("voice", status="idle")

    async def speak(self, text: str):
        """Generate speech from text via ElevenLabs."""
        self._is_speaking = True
        logger.info(f"ConversationManager speaking: {text}")
        await self.registry.emit("voice", status="speaking", text=text)
        
        # When speaking, we usually suppress VAD or STT processing 
        # to avoid echo unless echo cancellation is active
        try:
            # Future: Call elevenlabs_agent methods here
            # simulate speech duration
            await asyncio.sleep(len(text) * 0.05)
        finally:
            self._is_speaking = False
            await self.registry.emit("voice", status="idle")

