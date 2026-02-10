import asyncio
import logging
import json
import sounddevice as sd
import numpy as np
from deepgram import DeepgramClient
from src.llm.tool_definitions import ALL_TOOLS

logger = logging.getLogger(__name__)

class ConversationManager:
    """
    Orchestrates the voice interaction flow.

    Binds Deepgram (STT) and ElevenLabs (TTS/Agent) together,
    managing the listening state and broadcasting transcripts to the registry.
    """
    def __init__(self, registry):
        self.registry = registry
        self.stt_api_key = registry.config.deepgram.api_key
        self.tts = registry.elevenlabs
        self._is_listening = False
        self._is_speaking = False
        self._dg_connection = None
        self._audio_stream = None
        self._loop = asyncio.get_event_loop()

    async def start_listening(self):
        """Start the microphone listener and stream to Deepgram."""
        if self._is_listening:
            return

        self._is_listening = True
        logger.info("ConversationManager: Initializing STT stream...")
        
        try:
            client = DeepgramClient(self.stt_api_key)
            self._dg_connection = client.listen.live.v("1")

            def on_message(self_dg, result, **kwargs):
                sentence = result.channel.alternatives[0].transcript
                if not sentence:
                    return
                
                is_final = result.is_final
                # Use the loop to call the async broadcast
                asyncio.run_coroutine_threadsafe(
                    self.registry.broadcast_transcript(sentence, is_final=is_final),
                    self._loop
                )
                
                if is_final:
                    logger.info(f"STT Final: {sentence}")
                    # Trigger LLM processing for final sentences
                    asyncio.run_coroutine_threadsafe(
                        self._process_user_input(sentence),
                        self._loop
                    )

            def on_error(self_dg, error, **kwargs):
                logger.error(f"Deepgram Error: {error}")

            # Using string constants to avoid import issues
            self._dg_connection.on("Results", on_message)
            self._dg_connection.on("Error", on_error)

            options = {
                "model": "nova-2",
                "language": "en",
                "smart_format": True,
                "interim_results": True,
                "encoding": "linear16",
                "channels": 1,
                "sample_rate": 16000,
            }

            await self._dg_connection.start(options)

            # Start Microphone Stream
            def audio_callback(indata, frames, time, status):
                if status:
                    logger.warning(f"Audio stream status: {status}")
                if self._dg_connection:
                    self._dg_connection.send(indata.tobytes())

            self._audio_stream = sd.RawInputStream(
                samplerate=16000, 
                blocksize=2000, 
                device=None, 
                dtype='int16',
                channels=1, 
                callback=audio_callback
            )
            self._audio_stream.start()

            logger.info("ConversationManager: Mic active and streaming to Deepgram")
            await self.registry.emit("voice", status="listening")

        except Exception as e:
            logger.exception("Failed to start listening: %s", e)
            self._is_listening = False

            # Start Microphone Stream
            def audio_callback(indata, frames, time, status):
                if status:
                    logger.warning(f"Audio stream status: {status}")
                if self._dg_connection:
                    self._dg_connection.send(indata.tobytes())

            self._audio_stream = sd.RawInputStream(
                samplerate=16000, 
                blocksize=2000, 
                device=None, 
                dtype='int16',
                channels=1, 
                callback=audio_callback
            )
            self._audio_stream.start()

            logger.info("ConversationManager: Mic active and streaming to Deepgram")
            await self.registry.emit("voice", status="listening")

        except Exception as e:
            logger.exception("Failed to start listening: %s", e)
            self._is_listening = False

    async def stop_listening(self):
        """Stop the microphone listener."""
        self._is_listening = False
        
        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None
            
        if self._dg_connection:
            await self._dg_connection.finish()
            self._dg_connection = None

        logger.info("ConversationManager: Stopped listening")
        await self.registry.emit("voice", status="idle")

    async def _process_user_input(self, text: str):
        """Send finalized transcript to LLM and handle response/tools."""
        if self._is_speaking or not text.strip():
            return
            
        logger.info(f"Processing voice input: {text}")
        
        # Store user message in memory
        if self.registry.memory:
            await self.registry.memory.store_message(role="user", content=text, source="telegram_voice")

        try:
            # Get response from LLM via registry
            response_dict = await self.registry.llm.chat(
                messages=[
                    {"role": "system", "content": self.registry.config.elevenlabs.personality},
                    {"role": "user", "content": text}
                ],
                tools=ALL_TOOLS
            )
            
            tool_calls = response_dict.get("tool_calls", [])
            response = response_dict.get("content")

            # Handle Tool Calls
            if tool_calls:
                logger.info(f"LLM requested {len(tool_calls)} tool calls")
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    
                    # Execute tool
                    result = await self.registry.tools.invoke(name, **args)
                    
                    # Store tool result in memory (optional, but good for context)
                    if self.registry.memory:
                        await self.registry.memory.store_message(
                            role="system", 
                            content=f"Tool {name} result: {result}", 
                            source="system"
                        )

                # After tool execution, we might want to tell the user what happened
                # If there's no content, we trigger a second chat to summarize
                if not response:
                    followup = await self.registry.llm.chat(
                        messages=[
                            {"role": "system", "content": "You just executed tools requested by the user. Summarize what you did concisely for voice response."},
                            {"role": "user", "content": text},
                            {"role": "assistant", "content": "", "tool_calls": tool_calls},
                            {"role": "system", "content": f"Results: {result}"} # Simplification for single result
                        ]
                    )
                    response = followup.get("content")

            if response:
                # Store assistant response in memory
                if self.registry.memory:
                    await self.registry.memory.store_message(role="assistant", content=response, source="telegram_voice")
                
                await self.registry.broadcast_transcript(response, is_final=True)
                await self.speak(response)
                
        except Exception as e:
            logger.error(f"Error processing voice input: {e}")

    async def speak(self, text: str):
        """Generate speech from text via ElevenLabsAgent."""
        self._is_speaking = True
        logger.info(f"ConversationManager speaking: {text}")
        await self.registry.emit("voice", status="speaking", text=text)
        
        try:
            # Call the actual ElevenLabs client
            if self.registry.elevenlabs:
                await self.registry.elevenlabs.speak(text)
            else:
                # Fallback to simulation
                await asyncio.sleep(len(text) * 0.05)
        except Exception as e:
            logger.error(f"ElevenLabs TTS failed: {e}")
            # Fallback to simulation
            await asyncio.sleep(len(text) * 0.05)
        finally:
            self._is_speaking = False
            await self.registry.emit("voice", status="idle")

