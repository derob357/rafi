"""Telegram channel adapter.

Wraps python-telegram-bot into the ChannelAdapter interface.
Delegates all LLM processing to the shared MessageProcessor.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.channels.base import ChannelAdapter, ChannelMessage
from src.channels.processor import MessageProcessor
from src.config.loader import AppConfig
from src.db.supabase_client import SupabaseClient
from src.llm.llm_manager import LLMManager
from src.security.auth import verify_telegram_user
from src.security.sanitizer import (
    MAX_TELEGRAM_MESSAGE_LENGTH,
    MAX_VOICE_TRANSCRIPTION_LENGTH,
    detect_prompt_injection,
    sanitize_text,
)
from src.voice.deepgram_stt import DeepgramSTT

logger = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """Telegram channel adapter using python-telegram-bot polling."""

    channel_id = "telegram"

    def __init__(
        self,
        config: AppConfig,
        db: SupabaseClient,
        processor: MessageProcessor,
        deepgram_stt: DeepgramSTT,
        llm_manager: Optional[LLMManager] = None,
    ) -> None:
        self._config = config
        self._db = db
        self._processor = processor
        self._deepgram_stt = deepgram_stt
        self._llm_manager = llm_manager
        self._app: Optional[Application] = None

    def is_configured(self) -> bool:
        return bool(self._config.telegram.bot_token)

    async def start(self) -> None:
        app = self._build_application()
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("Telegram adapter polling started")

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram adapter stopped")
        except Exception as e:
            logger.error("Error stopping Telegram adapter: %s", e)

    async def send_text(self, to: str, text: str, **kwargs: Any) -> dict:
        if self._app is None:
            logger.error("Cannot send: Telegram app not initialized")
            return {"error": "not_initialized"}
        try:
            msg = await self._app.bot.send_message(chat_id=to, text=text)
            return {"message_id": msg.message_id}
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)
            return {"error": str(e)}

    async def send_media(
        self, to: str, text: str, media_url: str, **kwargs: Any
    ) -> dict:
        if self._app is None:
            return {"error": "not_initialized"}
        try:
            msg = await self._app.bot.send_photo(
                chat_id=to, photo=media_url, caption=text,
            )
            return {"message_id": msg.message_id}
        except Exception as e:
            logger.error("Failed to send Telegram media: %s", e)
            return {"error": str(e)}

    # -- Proactive messaging (used by heartbeat / scheduler) -----------------

    async def send_proactive(self, text: str) -> None:
        """Send a message to the authorized user without a prior inbound."""
        await self.send_text(to=str(self._config.telegram.user_id), text=text)

    # -- Internal helpers ----------------------------------------------------

    def _build_application(self) -> Application:
        builder = Application.builder().token(self._config.telegram.bot_token)
        app = builder.build()

        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(CommandHandler("settings", self._handle_settings))
        app.add_handler(CommandHandler("provider", self._handle_provider))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )

        self._app = app
        logger.info("Telegram bot application built")
        return app

    async def _handle_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not verify_telegram_user(update, self._config):
            return
        if update.message is None or update.message.text is None:
            return

        raw_text = update.message.text
        text = sanitize_text(raw_text, max_length=MAX_TELEGRAM_MESSAGE_LENGTH)
        if not text:
            await update.message.reply_text("I didn't catch that. Could you try again?")
            return

        if detect_prompt_injection(text):
            logger.warning("Prompt injection detected in Telegram message")
            await update.message.reply_text("I can't process that message.")
            return

        msg = ChannelMessage(
            channel="telegram",
            sender_id=str(update.effective_user.id) if update.effective_user else "",
            text=text,
            raw=update,
        )

        response = await self._processor.process(msg)
        await update.message.reply_text(response)

    async def _handle_voice(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not verify_telegram_user(update, self._config):
            return
        if update.message is None or update.message.voice is None:
            return

        await update.message.reply_text("Processing your voice message...")

        voice = update.message.voice
        voice_file = await voice.get_file()

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp_path = tmp.name
                await voice_file.download_to_drive(tmp_path)

            transcription = await self._deepgram_stt.transcribe_file(tmp_path)

            if not transcription or not transcription.strip():
                await update.message.reply_text(
                    "I couldn't understand that voice message. "
                    "Please try again or type your message."
                )
                return

            transcription = sanitize_text(
                transcription, max_length=MAX_VOICE_TRANSCRIPTION_LENGTH,
            )

            if detect_prompt_injection(transcription):
                logger.warning("Prompt injection detected in voice transcription")
                await update.message.reply_text("I can't process that message.")
                return

            msg = ChannelMessage(
                channel="telegram",
                sender_id=str(update.effective_user.id) if update.effective_user else "",
                text=transcription,
                raw=update,
            )

            response = await self._processor.process(msg)
            await update.message.reply_text(response)

        except Exception as e:
            logger.error("Voice message processing error: %s", e)
            await update.message.reply_text(
                "I had trouble processing that voice message. Please try again."
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not verify_telegram_user(update, self._config):
            return
        if update.message is None:
            return

        name = self._config.elevenlabs.agent_name
        client_name = self._config.client.name

        await update.message.reply_text(
            f"Hello {client_name}! I'm {name}, your personal assistant.\n\n"
            f"I can help you with:\n"
            f"- Calendar management\n"
            f"- Email reading and sending\n"
            f"- Tasks and notes\n"
            f"- Weather information\n"
            f"- Reminders and briefings\n\n"
            f"Just send me a message or voice note to get started!\n"
            f"Use /help for more info or /settings to view your settings."
        )

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not verify_telegram_user(update, self._config):
            return
        if update.message is None:
            return

        await update.message.reply_text(
            "Here's what I can do:\n\n"
            "Calendar:\n"
            '  "What\'s on my schedule today?"\n'
            '  "Schedule a meeting with John tomorrow at 3pm"\n\n'
            "Email:\n"
            '  "Do I have any unread emails?"\n'
            '  "Send an email to john@example.com"\n\n'
            "Tasks:\n"
            '  "Create a task: Review proposal"\n'
            '  "Show my pending tasks"\n\n'
            "Notes:\n"
            '  "Create a note about the meeting"\n'
            '  "Show my notes"\n\n'
            "Weather:\n"
            '  "What\'s the weather like?"\n\n'
            "Memory:\n"
            '  "What did we discuss about the project?"\n\n'
            "Settings commands:\n"
            '  "set quiet hours 10pm to 7am"\n'
            '  "set briefing time 8am"\n'
            '  "set reminder 15 minutes"\n'
            '  "set snooze 5 minutes"\n\n'
            "AI Provider:\n"
            "  /provider - Show current AI provider\n"
            "  /provider openai - Switch to OpenAI GPT-4o\n"
            "  /provider claude - Switch to Anthropic Claude\n"
            "  /provider groq - Switch to Groq (Llama)\n"
            "  /provider gemini - Switch to Google Gemini"
        )

    async def _handle_settings(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not verify_telegram_user(update, self._config):
            return
        if update.message is None:
            return

        db_settings = await self._db.select("settings")
        settings_map: dict[str, str] = {}
        for s in db_settings:
            settings_map[s.get("key", "")] = s.get("value", "")

        cfg = self._config.settings
        briefing = settings_map.get("morning_briefing_time", cfg.morning_briefing_time)
        quiet_start = settings_map.get("quiet_hours_start", cfg.quiet_hours_start)
        quiet_end = settings_map.get("quiet_hours_end", cfg.quiet_hours_end)
        reminder = settings_map.get("reminder_lead_minutes", str(cfg.reminder_lead_minutes))
        snooze = settings_map.get("min_snooze_minutes", str(cfg.min_snooze_minutes))
        tz = cfg.timezone

        await update.message.reply_text(
            f"Current Settings:\n\n"
            f"Morning briefing: {briefing}\n"
            f"Quiet hours: {quiet_start} - {quiet_end}\n"
            f"Reminder lead time: {reminder} minutes\n"
            f"Minimum snooze: {snooze} minutes\n"
            f"Timezone: {tz}\n\n"
            f"To change settings, use commands like:\n"
            f'  "set briefing time 7:30am"\n'
            f'  "set quiet hours 11pm to 6am"'
        )

    async def _handle_provider(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not verify_telegram_user(update, self._config):
            return
        if update.message is None:
            return

        if self._llm_manager is None:
            await update.message.reply_text("Provider switching is not available.")
            return

        args = context.args
        if not args:
            active = self._llm_manager.active_name
            available = self._llm_manager.available
            lines = []
            for p in available:
                marker = " (active)" if p == active else ""
                lines.append(f"  - {p}{marker}")
            await update.message.reply_text(
                f"Current provider: {active}\n\n"
                f"Available providers:\n" + "\n".join(lines) + "\n\n"
                f"Switch with: /provider <name>"
            )
            return

        requested = args[0].lower()
        try:
            new_name = self._llm_manager.switch(requested)
            await update.message.reply_text(f"Switched to: {new_name}")
        except ValueError as e:
            await update.message.reply_text(str(e))
