"""Learning service for continuous improvement.

Captures user satisfaction signals (explicit ratings, implicit sentiment),
stores them in Supabase, and periodically generates behavioral adjustments
that feed back into the system prompt.

Inspired by PAI's rating capture + AI Steering Rules pattern.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.db.supabase_client import SupabaseClient
from src.llm.provider import LLMProvider
from src.services.memory_files import MemoryFileService
from src.utils.async_utils import await_if_needed

logger = logging.getLogger(__name__)

# Patterns for explicit ratings (e.g., "8/10", "rating: 3", "score 7")
RATING_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s*/\s*10\b"),
    re.compile(r"\brat(?:ing|e)[\s:]+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bscore[\s:]+(\d{1,2})\b", re.IGNORECASE),
]

# Keywords suggesting negative sentiment
NEGATIVE_INDICATORS = [
    "wrong", "incorrect", "bad", "terrible", "awful", "useless",
    "not what i asked", "that's not right", "try again", "redo",
    "no that's wrong", "fail", "broken", "doesn't work",
]

# Keywords suggesting positive sentiment
POSITIVE_INDICATORS = [
    "perfect", "great", "excellent", "thanks", "thank you",
    "exactly", "that's right", "awesome", "love it", "nice",
    "well done", "good job",
]

ANALYSIS_PROMPT = """\
You are analyzing user feedback signals for an AI assistant named Rafi. \
Based on the feedback data below, generate 1-3 concise behavioral adjustments \
that would improve user satisfaction.

Each adjustment should be:
- Specific and actionable (not vague like "be better")
- Derived from patterns in the feedback (not speculation)
- Phrased as a directive (e.g., "Always confirm before sending emails")

Feedback signals (most recent first):
{feedback_data}

Return a JSON array of adjustment strings. If there are no clear patterns, return [].
"""


class LearningService:
    """Captures user feedback and generates behavioral adjustments."""

    def __init__(
        self,
        db: SupabaseClient,
        llm: LLMProvider,
        memory_files: MemoryFileService,
    ) -> None:
        self._db = db
        self._llm = llm
        self._memory_files = memory_files

    async def detect_and_store_feedback(
        self,
        user_message: str,
        assistant_response: str,
        source: str = "telegram_text",
    ) -> Optional[dict[str, Any]]:
        """Detect feedback signals in a user message and store them.

        Checks for:
        1. Explicit ratings (e.g., "8/10")
        2. Negative sentiment keywords
        3. Positive sentiment keywords

        Args:
            user_message: The user's message text.
            assistant_response: The preceding assistant response being rated.
            source: Message source channel.

        Returns:
            Stored feedback dict, or None if no signal detected.
        """
        signal = self._detect_signal(user_message)
        if not signal:
            return None

        feedback_data: dict[str, Any] = {
            "signal_type": signal["type"],
            "rating": signal.get("rating"),
            "sentiment": signal.get("sentiment"),
            "user_message": user_message[:500],
            "assistant_response": assistant_response[:500],
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            result = await await_if_needed(
                self._db.insert("feedback", feedback_data)
            )
            if result:
                logger.info(
                    "Feedback captured: type=%s, rating=%s, sentiment=%s",
                    signal["type"],
                    signal.get("rating"),
                    signal.get("sentiment"),
                )
                return result
        except Exception as e:
            logger.warning("Failed to store feedback: %s", e)

        return None

    def _detect_signal(self, text: str) -> Optional[dict[str, Any]]:
        """Detect a feedback signal in text.

        Returns:
            Dict with "type" ("explicit_rating" | "implicit_sentiment"),
            optional "rating" (int), and optional "sentiment" ("positive" | "negative").
        """
        # Check explicit ratings first
        for pattern in RATING_PATTERNS:
            match = pattern.search(text)
            if match:
                rating = int(match.group(1))
                if 1 <= rating <= 10:
                    return {
                        "type": "explicit_rating",
                        "rating": rating,
                        "sentiment": "positive" if rating >= 7 else "negative" if rating <= 3 else "neutral",
                    }

        # Check implicit sentiment
        lower = text.lower()

        for indicator in NEGATIVE_INDICATORS:
            if indicator in lower:
                return {
                    "type": "implicit_sentiment",
                    "sentiment": "negative",
                }

        for indicator in POSITIVE_INDICATORS:
            if indicator in lower:
                return {
                    "type": "implicit_sentiment",
                    "sentiment": "positive",
                }

        return None

    async def get_recent_feedback(
        self,
        days: int = 7,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent feedback signals.

        Args:
            days: Number of days to look back.
            limit: Maximum results.

        Returns:
            List of feedback dicts, most recent first.
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            result = await await_if_needed(
                self._db.select(
                    "feedback",
                    columns="*",
                    order_by="created_at",
                    order_desc=True,
                    limit=limit,
                )
            )
            if result:
                return [r for r in result if r.get("created_at", "") >= cutoff]
        except Exception as e:
            logger.warning("Failed to fetch feedback: %s", e)

        return []

    async def generate_adjustments(self) -> list[str]:
        """Analyze recent feedback and generate behavioral adjustments.

        Returns:
            List of adjustment directive strings.
        """
        feedback = await self.get_recent_feedback(days=14, limit=30)
        if len(feedback) < 3:
            logger.debug("Not enough feedback signals (%d) for analysis", len(feedback))
            return []

        # Format feedback for LLM
        lines = []
        for f in feedback:
            rating_str = f"rating={f['rating']}" if f.get("rating") else ""
            sentiment_str = f"sentiment={f.get('sentiment', '?')}"
            lines.append(
                f"- [{f.get('signal_type', '?')}] {rating_str} {sentiment_str}: "
                f"user said \"{f.get('user_message', '')[:200]}\" "
                f"in response to \"{f.get('assistant_response', '')[:200]}\""
            )

        prompt = ANALYSIS_PROMPT.format(feedback_data="\n".join(lines))

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            content = response.get("content", "[]")
            adjustments = self._parse_json_array(content)
            if adjustments:
                logger.info("Generated %d behavioral adjustments", len(adjustments))
                return adjustments
        except Exception as e:
            logger.warning("Adjustment generation failed: %s", e)

        return []

    async def apply_adjustments_to_memory(self, adjustments: list[str]) -> bool:
        """Write behavioral adjustments to MEMORY.md under a Learning section.

        Args:
            adjustments: List of adjustment directive strings.

        Returns:
            True if written successfully.
        """
        if not adjustments:
            return False

        for adj in adjustments:
            self._memory_files.append_to_memory("Behavioral Adjustments", adj)

        logger.info("Applied %d adjustments to MEMORY.md", len(adjustments))
        return True

    def get_adjustments_for_prompt(self) -> str:
        """Load current behavioral adjustments from MEMORY.md for system prompt injection.

        Returns:
            Formatted adjustment text, or empty string if none.
        """
        memory = self._memory_files.load_memory()
        if "## Behavioral Adjustments" not in memory:
            return ""

        # Extract the adjustments section
        lines = memory.split("\n")
        in_section = False
        adjustments = []
        for line in lines:
            if line.strip().startswith("## Behavioral Adjustments"):
                in_section = True
                continue
            if in_section:
                if line.strip().startswith("## "):
                    break
                if line.strip().startswith("- "):
                    adjustments.append(line.strip())

        if not adjustments:
            return ""

        return "## Behavioral Adjustments (from user feedback)\n" + "\n".join(adjustments)

    @staticmethod
    def _parse_json_array(text: str) -> list[str]:
        """Extract a JSON array from LLM response text."""
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return [str(item) for item in result]
        except json.JSONDecodeError:
            pass

        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start : end + 1])
                if isinstance(result, list):
                    return [str(item) for item in result]
            except json.JSONDecodeError:
                pass

        return []
