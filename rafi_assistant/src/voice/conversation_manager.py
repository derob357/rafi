import asyncio
import logging
import json
import re
import sounddevice as sd
import numpy as np
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV1ResultsEvent
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
        self._current_speech_text = None
        self._last_barge_in_time = 0
        self._last_speech_end_time = 0  # To handle post-speech cooldown
        self._speech_history = []        # To track recent responses for echo detection
        self._dg_client = None
        self._dg_connection = None
        self._audio_stream = None
        self._loop = asyncio.get_event_loop()
        self._process_lock = asyncio.Lock()  # Prevent concurrent processing of voice input
        self._last_final_text = ""
        self._last_final_time = 0
        self._min_barge_in_words = 1
        self._echo_token_threshold = 0.85

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for echo checks (lowercase, strip punctuation)."""
        if not text:
            return ""
        normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _token_overlap_ratio(left: str, right: str) -> float:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = left_tokens & right_tokens
        return len(overlap) / max(len(left_tokens), len(right_tokens))

    def _is_echo_text(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        candidates = []
        if self._current_speech_text:
            candidates.append(self._current_speech_text)
        candidates.extend(self._speech_history[-2:])

        for candidate in candidates:
            candidate_norm = self._normalize_text(candidate)
            if not candidate_norm:
                continue
            if normalized in candidate_norm or candidate_norm in normalized:
                return True
            if len(normalized.split()) >= 3:
                overlap = self._token_overlap_ratio(normalized, candidate_norm)
                if overlap >= self._echo_token_threshold:
                    return True
        return False

    async def start_listening(self):
        """Start the microphone listener and stream to Deepgram."""
        if self._is_listening:
            return

        self._is_listening = True
        logger.info("ConversationManager: Initializing STT stream...")
        
        try:
            self._dg_client = AsyncDeepgramClient(api_key=self.stt_api_key)
            
            # Using the async with context manager for the connection
            # Note: SDK 5.x uses strings for most options in the connect method
            self._dg_connection_context = self._dg_client.listen.v1.connect(
                model="nova-2",
                language="en",
                smart_format="true",
                interim_results="true",
                encoding="linear16",
                channels="1",
                sample_rate="16000",
                endpointing="300",
            )
            
            self._dg_connection = await self._dg_connection_context.__aenter__()

            async def on_message(message, **kwargs):
                if not isinstance(message, ListenV1ResultsEvent):
                    return
                    
                sentence = message.channel.alternatives[0].transcript
                if not sentence or not sentence.strip():
                    return
                
                is_final = message.is_final
                now = asyncio.get_event_loop().time()

                # COOLDOWN: Reject transcripts right after we stop speaking,
                # unless we just barged in (let the user finish their interruption).
                recent_barge_in = now - self._last_barge_in_time < 1.0
                if not self._is_speaking and not recent_barge_in and (now - self._last_speech_end_time < 1.0):
                    logger.debug(f"Ignoring post-speech cooldown transcript: '{sentence}'")
                    return

                # BARGE-IN: If assistant is speaking and we detect non-empty transcript, stop playback immediately
                if self._is_speaking:
                    if len(sentence.split()) < self._min_barge_in_words:
                        return

                    if self._is_echo_text(sentence):
                        logger.debug(f"Ignoring self-echo during playback: {sentence}")
                        return

                    logger.info(f"Barge-in detected: interrupting playback for: '{sentence}'")
                    self._last_barge_in_time = now
                    await self.stop_speaking()

                # Broadcast the transcript to the UI
                await self.registry.broadcast_transcript(sentence, is_final=is_final)
                
                if is_final:
                    # DEDUPLICATION: Deepgram sometimes sends multiple identical final results
                    if sentence == self._last_final_text and (now - self._last_final_time < 1.0):
                        return
                    
                    self._last_final_text = sentence
                    self._last_final_time = now
                    
                    logger.info(f"STT Final: {sentence}")
                    # Trigger LLM processing for final sentences in background
                    asyncio.create_task(self._process_user_input(sentence))

            async def on_error(error, **kwargs):
                logger.error(f"Deepgram Error: {error}")

            # Register handlers
            self._dg_connection.on(EventType.MESSAGE, on_message)
            self._dg_connection.on(EventType.ERROR, on_error)

            # Start processing messages from the websocket in the background
            asyncio.create_task(self._dg_connection.start_listening())

            # Start Microphone Stream
            def audio_callback(indata, frames, time, status):
                if status:
                    logger.warning(f"Audio stream status: {status}")
                
                # NOTE: We no longer return early when self._is_speaking is True
                # to allow barge-in support. Software echo-detection in on_message
                # handles the feedback prevention.

                if self._dg_connection:
                    # Send bytes to Deepgram - converting CFFI buffer to bytes
                    asyncio.run_coroutine_threadsafe(
                        self._dg_connection.send_media(bytes(indata)), 
                        self._loop
                    )

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
            if self._dg_connection:
                self._dg_connection = None

    async def stop_listening(self):
        """Stop the microphone listener."""
        self._is_listening = False
        
        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None
            
        if self._dg_connection:
            try:
                # Exit the context manager to close the connection properly
                await self._dg_connection_context.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error closing Deepgram connection: {e}")
            finally:
                self._dg_connection = None
                self._dg_connection_context = None

        logger.info("ConversationManager: Stopped listening")
        await self.registry.emit("voice", status="idle")

    async def stop_speaking(self):
        """Stop current TTS playback for barge-in support."""
        if self._is_speaking and self.tts:
            await self.tts.stop()
            self._is_speaking = False
            self._last_speech_end_time = asyncio.get_event_loop().time()
            await self.registry.emit("voice", status="idle")

    async def process_text_input(self, text: str):
        """Process text input from the desktop UI (no TTS).

        Sends the text through the LLM, handles tool calls, and
        broadcasts the response to the transcript queue for display.
        """
        if not text.strip():
            return

        logger.info("Processing text input: %s", text)

        # Store user message in memory
        if self.registry.memory:
            await self.registry.memory.store_message(role="user", content=text, source="desktop_text")

        try:
            response_dict = await self.registry.llm.chat(
                messages=[
                    {"role": "system", "content": self.registry.config.elevenlabs.personality},
                    {"role": "user", "content": text},
                ],
                tools=ALL_TOOLS,
            )

            tool_calls = response_dict.get("tool_calls", [])
            response = response_dict.get("content")

            if tool_calls:
                logger.info("LLM requested %d tool calls", len(tool_calls))
                result = None
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    result = await self.registry.tools.invoke(name, **args)

                if not response and result is not None:
                    followup = await self.registry.llm.chat(
                        messages=[
                            {"role": "system", "content": "Summarize what you just did concisely."},
                            {"role": "user", "content": text},
                            {"role": "system", "content": f"Tool result: {result}"},
                        ]
                    )
                    response = followup.get("content")

            if response:
                # Store assistant response in memory
                if self.registry.memory:
                    await self.registry.memory.store_message(role="assistant", content=response, source="desktop_text")
                # Broadcast with role so UI shows it as RAFI
                await self.registry.transcript_queue.put({"text": response, "role": "assistant", "is_final": True})
            else:
                await self.registry.transcript_queue.put({"text": "I'm not sure how to respond to that.", "role": "assistant", "is_final": True})

        except Exception as e:
            logger.error("Error processing text input: %s", e)
            await self.registry.transcript_queue.put({"text": f"Error: {e}", "role": "assistant", "is_final": True})

    async def _process_user_input(self, text: str):
        """Send finalized transcript to LLM and handle response/tools."""
        if not text.strip():
            return

        async with self._process_lock:
            # Re-check is_speaking inside lock, but only if not a barge-in
            if self._is_speaking:
                logger.debug("Still speaking, ignoring transcript for new process")
                return

            # MINIMUM WORD COUNT: Filter out fragments logic
            words = text.split()
            if len(words) < 2:
                logger.debug(f"Ignoring single-word transcript fragment: '{text}'")
                return

            # ECHO PROTECTION: Ignore assistant echo even if punctuation differs.
            now = asyncio.get_event_loop().time()
            if self._is_echo_text(text):
                logger.info(f"Ignoring echo transcript: '{text}'")
                return

            if now - self._last_barge_in_time < 2.0 and self._is_echo_text(text):
                logger.info(f"Ignoring echo transcript after barge-in: '{text}'")
                return

            logger.info(f"Processing voice input: {text}")
            
            # Store user message in memory
            if self.registry.memory:
                await self.registry.memory.store_message(role="user", content=text, source="desktop_voice")

            try:
                # Inform the LLM about the voice context
                system_prompt = self.registry.config.elevenlabs.personality
                voice_context = "\n\nNOTE: The user is speaking via microphone. You should be concise and conversational. Respond as if you can hear them perfectly."
                
                # Get response from LLM via registry
                response_dict = await self.registry.llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt + voice_context},
                        {"role": "user", "content": text}
                    ],
                    tools=ALL_TOOLS
                )
                
                tool_calls = response_dict.get("tool_calls", [])
                response = response_dict.get("content")

                # Handle Tool Calls
                if tool_calls:
                    logger.info(f"LLM requested {len(tool_calls)} tool calls")
                    result = None
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
                    # If there's no content, we trigger a second chat to summarize.
                    # We pass the tool result in a way that doesn't violate OpenAI's 
                    # requirement that tool_calls be followed by tool results.
                    if not response:
                        followup = await self.registry.llm.chat(
                            messages=[
                                {"role": "system", "content": f"You just executed a tool: {name}. Results: {result}. Briefly summarize the outcome for a voice response."},
                                {"role": "user", "content": text},
                            ]
                        )
                        response = followup.get("content")

                if response:
                    # Store assistant response in memory
                    if self.registry.memory:
                        await self.registry.memory.store_message(role="assistant", content=response, source="desktop_voice")
                    
                    await self.registry.broadcast_transcript(response, is_final=True, role="assistant")
                    await self.speak(response)
                    
            except Exception as e:
                logger.error(f"Error processing voice input: {e}")

    async def speak(self, text: str):
        """Generate speech from text via ElevenLabsAgent."""
        self._is_speaking = True
        self._current_speech_text = text
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
            self._last_speech_end_time = asyncio.get_event_loop().time()
            self._speech_history.append(text)
            if len(self._speech_history) > 5:
                self._speech_history.pop(0)
            self._current_speech_text = None
            await self.registry.emit("voice", status="idle")

