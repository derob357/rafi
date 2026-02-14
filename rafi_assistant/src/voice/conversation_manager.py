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

    Echo prevention strategy:
    - While Rafi is speaking, the mic feed to Deepgram is PAUSED so we never
      transcribe our own output.
    - Barge-in is detected via audio energy (RMS) in the audio callback.
      If the energy exceeds a threshold during speech, we stop TTS, wait for
      the echo to decay, then resume the Deepgram feed.
    - After speech ends, a short cooldown prevents residual echo from being
      processed.
    """

    # Audio energy threshold for barge-in detection (RMS of int16 samples).
    # Typical quiet room ~200-500, normal speech ~2000-5000.
    BARGE_IN_RMS_THRESHOLD = 3000
    # Number of consecutive high-energy frames needed to confirm barge-in
    BARGE_IN_FRAME_COUNT = 3
    # Seconds to wait after speech ends before sending audio to Deepgram
    POST_SPEECH_SILENCE_SEC = 0.5
    # Seconds to ignore transcripts after speech ends
    POST_SPEECH_COOLDOWN_SEC = 2.0
    # Echo token overlap threshold (lower = more aggressive echo rejection)
    ECHO_TOKEN_THRESHOLD = 0.55

    def __init__(self, registry):
        self.registry = registry
        self.stt_api_key = registry.config.deepgram.api_key
        self.tts = registry.elevenlabs
        self._is_listening = False
        self._is_speaking = False
        self._current_speech_text = None
        self._last_barge_in_time = 0
        self._last_speech_end_time = 0
        self._speech_history = []
        self._dg_client = None
        self._dg_connection = None
        self._audio_stream = None
        self._loop = asyncio.get_event_loop()
        self._process_lock = asyncio.Lock()
        self._current_process_task: asyncio.Task | None = None
        self._last_final_text = ""
        self._last_final_time = 0
        self._min_barge_in_words = 2
        # Counter for consecutive high-energy audio frames (barge-in detection)
        self._high_energy_frames = 0
        # Flag: True while we're in the post-speech silence window
        # (mic is paused briefly so the speaker echo decays)
        self._post_speech_pause = False

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
        candidates.extend(self._speech_history[-3:])

        for candidate in candidates:
            candidate_norm = self._normalize_text(candidate)
            if not candidate_norm:
                continue
            if normalized in candidate_norm or candidate_norm in normalized:
                return True
            if len(normalized.split()) >= 3:
                overlap = self._token_overlap_ratio(normalized, candidate_norm)
                if overlap >= self.ECHO_TOKEN_THRESHOLD:
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

                # POST-SPEECH COOLDOWN: Reject transcripts shortly after speaking
                # to filter out residual echo that Deepgram may still be processing.
                if not self._is_speaking and (now - self._last_speech_end_time < self.POST_SPEECH_COOLDOWN_SEC):
                    # Allow through only if it's clearly NOT echo
                    if self._is_echo_text(sentence):
                        logger.debug("Ignoring post-speech echo transcript: '%s'", sentence)
                        return

                # While speaking, all transcripts should be paused by the audio
                # callback (mic is muted). If one slips through, reject it.
                if self._is_speaking:
                    logger.debug("Ignoring transcript during speech: '%s'", sentence)
                    return

                # Broadcast the transcript to the UI
                await self.registry.broadcast_transcript(sentence, is_final=is_final)

                if is_final:
                    # DEDUPLICATION: Deepgram sometimes sends multiple identical final results
                    if sentence == self._last_final_text and (now - self._last_final_time < 2.0):
                        logger.debug("Ignoring duplicate final transcript: '%s'", sentence)
                        return

                    self._last_final_text = sentence
                    self._last_final_time = now

                    logger.info("STT Final: %s", sentence)

                    # Cancel any previous processing task — only the latest
                    # user utterance should be processed.
                    if self._current_process_task and not self._current_process_task.done():
                        self._current_process_task.cancel()
                    self._current_process_task = asyncio.create_task(
                        self._process_user_input(sentence)
                    )

            async def on_error(error, **kwargs):
                logger.error("Deepgram Error: %s", error)

            self._dg_connection.on(EventType.MESSAGE, on_message)
            self._dg_connection.on(EventType.ERROR, on_error)

            asyncio.create_task(self._dg_connection.start_listening())

            def audio_callback(indata, frames, time, status):
                if status:
                    logger.warning("Audio stream status: %s", status)

                # While speaking or in post-speech pause, DON'T send audio to
                # Deepgram.  This prevents the echo loop entirely.
                if self._is_speaking or self._post_speech_pause:
                    # Barge-in detection via audio energy:
                    # If the user speaks loudly enough over Rafi's playback,
                    # we detect it and stop TTS.
                    if self._is_speaking:
                        audio_data = np.frombuffer(indata, dtype=np.int16)
                        rms = float(np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)))
                        if rms > self.BARGE_IN_RMS_THRESHOLD:
                            self._high_energy_frames += 1
                            if self._high_energy_frames >= self.BARGE_IN_FRAME_COUNT:
                                logger.info("Barge-in detected via audio energy (RMS=%.0f)", rms)
                                self._high_energy_frames = 0
                                asyncio.run_coroutine_threadsafe(
                                    self._handle_barge_in(), self._loop
                                )
                        else:
                            self._high_energy_frames = 0
                    return

                if self._dg_connection:
                    asyncio.run_coroutine_threadsafe(
                        self._dg_connection.send_media(bytes(indata)),
                        self._loop,
                    )

            self._audio_stream = sd.RawInputStream(
                samplerate=16000,
                blocksize=2000,
                device=None,
                dtype="int16",
                channels=1,
                callback=audio_callback,
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
                await self._dg_connection_context.__aexit__(None, None, None)
            except Exception as e:
                logger.error("Error closing Deepgram connection: %s", e)
            finally:
                self._dg_connection = None
                self._dg_connection_context = None

        logger.info("ConversationManager: Stopped listening")
        await self.registry.emit("voice", status="idle")

    async def _handle_barge_in(self):
        """Handle a barge-in event: stop speaking and cancel pending work."""
        logger.info("Handling barge-in: stopping speech and cancelling pending tasks")
        self._last_barge_in_time = asyncio.get_event_loop().time()

        # Stop TTS playback
        await self.stop_speaking()

        # Cancel any pending LLM processing so the echo response doesn't play
        if self._current_process_task and not self._current_process_task.done():
            self._current_process_task.cancel()
            self._current_process_task = None

    async def stop_speaking(self):
        """Stop current TTS playback for barge-in support."""
        if self._is_speaking and self.tts:
            await self.tts.stop()
            self._is_speaking = False
            self._last_speech_end_time = asyncio.get_event_loop().time()
            await self.registry.emit("voice", status="idle")

            # Brief pause before resuming Deepgram feed so the speaker
            # echo decays and doesn't get transcribed.
            self._post_speech_pause = True
            await asyncio.sleep(self.POST_SPEECH_SILENCE_SEC)
            self._post_speech_pause = False

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
                if self.registry.memory:
                    await self.registry.memory.store_message(role="assistant", content=response, source="desktop_text")
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

        try:
            async with self._process_lock:
                # Re-check: if we started speaking since this task was queued, bail.
                if self._is_speaking:
                    logger.debug("Still speaking, skipping: '%s'", text)
                    return

                # MINIMUM WORD COUNT: Filter out fragments
                words = text.split()
                if len(words) < 2:
                    logger.debug("Ignoring single-word transcript fragment: '%s'", text)
                    return

                # ECHO PROTECTION: Reject text that matches recent Rafi output
                if self._is_echo_text(text):
                    logger.info("Ignoring echo transcript: '%s'", text)
                    return

                logger.info("Processing voice input: %s", text)

                # Store user message in memory
                if self.registry.memory:
                    await self.registry.memory.store_message(role="user", content=text, source="desktop_voice")

                # Get response from LLM
                system_prompt = self.registry.config.elevenlabs.personality
                voice_context = (
                    "\n\nNOTE: The user is speaking via microphone. Be concise "
                    "and conversational. Respond as if you can hear them perfectly."
                )

                response_dict = await self.registry.llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt + voice_context},
                        {"role": "user", "content": text},
                    ],
                    tools=ALL_TOOLS,
                )

                tool_calls = response_dict.get("tool_calls", [])
                response = response_dict.get("content")

                # Handle Tool Calls
                if tool_calls:
                    logger.info("LLM requested %d tool calls", len(tool_calls))
                    result = None
                    for tc in tool_calls:
                        name = tc["function"]["name"]
                        args = json.loads(tc["function"]["arguments"])
                        result = await self.registry.tools.invoke(name, **args)

                        if self.registry.memory:
                            await self.registry.memory.store_message(
                                role="system",
                                content=f"Tool {name} result: {result}",
                                source="system",
                            )

                    if not response and result is not None:
                        followup = await self.registry.llm.chat(
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        f"You just executed a tool: {name}. "
                                        f"Results: {result}. "
                                        "Briefly summarize the outcome for a voice response."
                                    ),
                                },
                                {"role": "user", "content": text},
                            ]
                        )
                        response = followup.get("content")

                if response:
                    if self.registry.memory:
                        await self.registry.memory.store_message(
                            role="assistant", content=response, source="desktop_voice"
                        )

                    await self.registry.broadcast_transcript(response, is_final=True, role="assistant")
                    await self.speak(response)

        except asyncio.CancelledError:
            logger.info("Processing cancelled for: '%s'", text)
        except Exception as e:
            logger.error("Error processing voice input: %s", e)

    async def speak(self, text: str):
        """Generate speech from text via ElevenLabsAgent."""
        self._is_speaking = True
        self._current_speech_text = text
        self._high_energy_frames = 0
        logger.info("ConversationManager speaking: %s", text)
        await self.registry.emit("voice", status="speaking", text=text)

        try:
            if self.registry.elevenlabs:
                await self.registry.elevenlabs.speak(text)
            else:
                await asyncio.sleep(len(text) * 0.05)
        except asyncio.CancelledError:
            logger.info("Speech cancelled")
        except Exception as e:
            logger.error("ElevenLabs TTS failed: %s", e)
        finally:
            self._is_speaking = False
            self._last_speech_end_time = asyncio.get_event_loop().time()
            self._speech_history.append(text)
            if len(self._speech_history) > 5:
                self._speech_history.pop(0)
            self._current_speech_text = None
            self._high_energy_frames = 0

            # Brief pause before resuming mic feed so speaker echo decays
            self._post_speech_pause = True
            await asyncio.sleep(self.POST_SPEECH_SILENCE_SEC)
            self._post_speech_pause = False

            await self.registry.emit("voice", status="idle")
