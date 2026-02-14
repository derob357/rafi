"""Automated memory promotion job.

Runs periodically to review daily session logs and promote important
insights to long-term memory (MEMORY.md) and user preferences (USER.md).

Solves the "context rot" problem by ensuring valuable conversation
insights are preserved beyond the daily log lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any

from src.llm.provider import LLMProvider
from src.services.memory_files import MemoryFileService

logger = logging.getLogger(__name__)

PROMOTION_PROMPT = """\
You are a memory curator for a personal AI assistant. Review the following daily \
conversation log and extract insights worth preserving in long-term memory.

Categories to extract:
1. **decisions** — Decisions the user made or preferences they expressed
2. **facts** — Key facts about the user's life, work, or relationships
3. **preferences** — Communication style, tool usage, or scheduling preferences
4. **projects** — Ongoing projects or goals mentioned

Rules:
- Only extract information that is reliably true (not one-off requests)
- Skip small talk, greetings, and transient requests
- Each insight should be a single concise sentence
- If nothing is worth promoting, return an empty object

Return a JSON object:
{{
  "decisions": ["insight1", ...],
  "facts": ["insight1", ...],
  "preferences": {{"key": "value", ...}},
  "projects": ["insight1", ...]
}}

Daily log:
{daily_log}

Existing memory (avoid duplicates):
{existing_memory}
"""


class MemoryPromotionJob:
    """Promotes insights from daily logs to long-term memory."""

    def __init__(
        self,
        llm: LLMProvider,
        memory_files: MemoryFileService,
    ) -> None:
        self._llm = llm
        self._memory_files = memory_files

    async def run(self) -> None:
        """Execute one promotion cycle.

        Reviews recent daily logs and promotes valuable insights.
        Called by APScheduler (recommended: once daily, e.g., 23:00).
        """
        logs = self._memory_files.list_daily_logs(limit=3)
        if not logs:
            logger.debug("No daily logs to review for promotion")
            return

        existing_memory = self._memory_files.load_memory()
        promoted_count = 0

        for date_str, content in logs:
            # Skip logs that already have a summary (already processed)
            if "## Daily Summary" in content:
                continue

            # Skip very short logs (less than 4 exchanges)
            exchange_count = content.count("**User**") + content.count("**Rafi**")
            if exchange_count < 4:
                logger.debug("Skipping short log for %s (%d exchanges)", date_str, exchange_count)
                continue

            insights = await self._extract_insights(content, existing_memory)
            if insights:
                count = await self._apply_insights(insights)
                promoted_count += count

            # Write a summary so we don't re-process this log
            if exchange_count >= 4:
                summary = f"Reviewed for memory promotion. {promoted_count} insights promoted."
                await self._memory_files.write_daily_summary(summary, date_str)

        if promoted_count > 0:
            logger.info("Memory promotion complete: %d insights promoted", promoted_count)
        else:
            logger.debug("Memory promotion: no new insights to promote")

    async def _extract_insights(
        self,
        daily_log: str,
        existing_memory: str,
    ) -> dict[str, Any]:
        """Use LLM to extract promotable insights from a daily log."""
        # Truncate very long logs
        if len(daily_log) > 8000:
            daily_log = daily_log[:8000] + "\n... (truncated)"
        if len(existing_memory) > 4000:
            existing_memory = existing_memory[:4000] + "\n... (truncated)"

        prompt = PROMOTION_PROMPT.format(
            daily_log=daily_log,
            existing_memory=existing_memory,
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
            )
            content = response.get("content", "{}")
            return self._parse_json_object(content)
        except Exception as e:
            logger.warning("Insight extraction failed: %s", e)
            return {}

    async def _apply_insights(self, insights: dict[str, Any]) -> int:
        """Apply extracted insights to memory files.

        Returns:
            Number of insights applied.
        """
        count = 0

        # Decisions → MEMORY.md "Decisions & Lessons" section
        for decision in insights.get("decisions", []):
            if decision and isinstance(decision, str):
                self._memory_files.append_to_memory("Decisions & Lessons", decision)
                count += 1

        # Facts → MEMORY.md "Key Facts" section
        for fact in insights.get("facts", []):
            if fact and isinstance(fact, str):
                self._memory_files.append_to_memory("Key Facts", fact)
                count += 1

        # Preferences → USER.md
        prefs = insights.get("preferences", {})
        if isinstance(prefs, dict):
            for key, value in prefs.items():
                if key and value and isinstance(key, str) and isinstance(value, str):
                    self._memory_files.update_user_preference(key, value)
                    count += 1

        # Projects → MEMORY.md "Ongoing Projects" section
        for project in insights.get("projects", []):
            if project and isinstance(project, str):
                self._memory_files.append_to_memory("Ongoing Projects", project)
                count += 1

        return count

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        """Extract a JSON object from LLM response text."""
        import json

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start : end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return {}
