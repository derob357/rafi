import asyncio
import logging
from typing import Optional

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
        self._listening_task: Optional[asyncio.Task] = None
        self._vad_task: Optional[asyncio.Task] = None
        self._is_listening = False
        self._is_speaking = False

    async def start_listening(self):
        """Start the microphone listener and stream to Deepgram."""
        if self._is_listening:
            return
        
        self._is_listening = True
        logger.info("ConversationManager: Started listening")
        
        # In a real multimodal ADA implementation, we run a VAD loop
        # to detect when the user starts/stops talking
        self._listening_task = asyncio.create_task(self._mock_listening_loop())
        self._vad_task = asyncio.create_task(self._vad_monitoring_loop())

    async def stop_listening(self):
        """Stop the microphone listener."""
        self._is_listening = False
        if self._listening_task:
            self._listening_task.cancel()
        if self._vad_task:
            self._vad_task.cancel()
        self._listening_task = None
        self._vad_task = None
        logger.info("ConversationManager: Stopped listening")

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

    async def _vad_monitoring_loop(self):
        """
        Monitor audio for voice activity detection.
        
        This manages the 'half-duplex' nature of the conversation.
        """
        try:
            while self._is_listening:
                # Placeholder for webrtcvad logic
                await asyncio.sleep(0.1)
                if self._is_speaking:
                    continue
                # Signal to UI that voice is detected (lighting up green etc)
        except asyncio.CancelledError:
            pass

    async def _mock_listening_loop(self):
        """Temporary mock to demonstrate transcript flow to UI."""
        try:
            while self._is_listening:
                # Simulate a transcript every 5 seconds for testing UI flow
                await asyncio.sleep(5)
                transcript = "I am a mock transcript from ConversationManager."
                await self.registry.broadcast_transcript(transcript, is_final=True)
        except asyncio.CancelledError:
            pass
