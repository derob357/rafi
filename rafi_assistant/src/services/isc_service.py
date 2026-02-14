"""ISC (Ideal State Criteria) service.

Generates binary-testable success criteria for tool-calling tasks,
inspired by PAI's Algorithm. Before executing tools, the LLM generates
criteria that define what "done" looks like. After execution, criteria
are verified with evidence.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

ISC_GENERATION_PROMPT = """\
You are an ISC (Ideal State Criteria) generator. Given a user request that requires \
tool use, generate a list of binary-testable success criteria.

Rules:
- Each criterion must be a state, not an action (e.g., "Event exists on calendar" not "Create event")
- Each criterion must be exactly measurable with YES/NO
- Each criterion should address one concern only
- Keep criteria minimal — only what's needed to verify the task is complete
- Return JSON array of strings, nothing else

User request: {user_message}
Available tools: {tool_names}
"""

ISC_VERIFY_PROMPT = """\
You are a verification engine. Given the original criteria and the tool execution results, \
verify each criterion.

For each criterion, respond with:
- "YES" if the evidence confirms the criterion is met
- "NO" if the evidence shows the criterion is not met

Return a JSON object mapping each criterion to "YES" or "NO" with a brief evidence note.

Criteria: {criteria}
Tool results: {tool_results}
"""


class ISCService:
    """Generates and verifies Ideal State Criteria for task execution."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def should_generate_isc(self, message: str, has_tools: bool) -> bool:
        """Determine if this message warrants ISC generation.

        ISC is generated for actionable requests that will use tools.
        Conversational messages, greetings, and simple questions skip ISC.
        """
        if not has_tools:
            return False

        action_indicators = [
            "create", "add", "schedule", "send", "update", "delete",
            "set", "change", "remind", "book", "cancel", "move",
            "make", "write", "compose", "draft", "plan",
        ]
        lower = message.lower()
        return any(word in lower for word in action_indicators)

    async def generate_criteria(
        self,
        user_message: str,
        tool_names: list[str],
    ) -> list[str]:
        """Generate ISC criteria for a user request.

        Args:
            user_message: The user's request text.
            tool_names: Names of available tools.

        Returns:
            List of binary-testable criteria strings.
        """
        prompt = ISC_GENERATION_PROMPT.format(
            user_message=user_message,
            tool_names=", ".join(tool_names),
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.get("content", "[]")
            # Extract JSON from response
            criteria = self._parse_json_array(content)
            if criteria:
                logger.info("Generated %d ISC criteria for: %s", len(criteria), user_message[:50])
                return criteria
        except Exception as e:
            logger.warning("ISC generation failed, proceeding without: %s", e)

        return []

    async def verify_criteria(
        self,
        criteria: list[str],
        tool_results: list[dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Verify ISC criteria against tool execution results.

        Args:
            criteria: List of criteria to verify.
            tool_results: List of {"tool": name, "result": output} dicts.

        Returns:
            Dict mapping each criterion to {"status": "YES"/"NO", "evidence": str}.
        """
        if not criteria:
            return {}

        results_text = "\n".join(
            f"- {r['tool']}: {r['result'][:500]}" for r in tool_results
        )

        prompt = ISC_VERIFY_PROMPT.format(
            criteria=json.dumps(criteria),
            tool_results=results_text,
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.get("content", "{}")
            verification = self._parse_json_object(content)
            if verification:
                passed = sum(1 for v in verification.values() if isinstance(v, str) and v.upper() == "YES")
                logger.info(
                    "ISC verification: %d/%d criteria passed",
                    passed,
                    len(criteria),
                )
                return {
                    c: {"status": v if isinstance(v, str) else "YES", "evidence": ""}
                    for c, v in verification.items()
                }
        except Exception as e:
            logger.warning("ISC verification failed: %s", e)

        return {c: {"status": "UNVERIFIED", "evidence": ""} for c in criteria}

    def format_verification_summary(
        self,
        verification: dict[str, dict[str, str]],
    ) -> str:
        """Format verification results as a human-readable summary."""
        if not verification:
            return ""

        lines = []
        all_passed = True
        for criterion, result in verification.items():
            status = result.get("status", "UNVERIFIED")
            icon = "+" if status.upper() == "YES" else "-"
            if status.upper() != "YES":
                all_passed = False
            lines.append(f"[{icon}] {criterion}")

        if all_passed:
            return ""  # Don't add noise when everything passes
        return "Verification:\n" + "\n".join(lines)

    @staticmethod
    def _parse_json_array(text: str) -> list[str]:
        """Extract a JSON array from LLM response text."""
        # Try direct parse
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return [str(item) for item in result]
        except json.JSONDecodeError:
            pass

        # Try to find JSON array in text
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

    @staticmethod
    def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
        """Extract a JSON object from LLM response text."""
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

        return None
