"""Skill discovery, parsing, and eligibility filtering.

Scans the skills/ directory for SKILL.md files, parses YAML frontmatter,
checks environment variable requirements, and builds the tool list for
eligible skills.

Inspired by OpenClaw's skill registry: drop a SKILL.md file in a directory
and it's instantly available.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from src.skills.types import Skill

logger = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Regex to split YAML frontmatter from markdown body
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse_skill_file(skill_path: Path) -> Optional[Skill]:
    """Parse a SKILL.md file into a Skill object.

    Args:
        skill_path: Path to the SKILL.md file.

    Returns:
        Parsed Skill, or None if parsing fails.
    """
    try:
        content = skill_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read skill file %s: %s", skill_path, e)
        return None

    match = FRONTMATTER_RE.match(content)
    if not match:
        logger.warning("No YAML frontmatter in %s", skill_path)
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in %s: %s", skill_path, e)
        return None

    if not isinstance(frontmatter, dict):
        logger.warning("Frontmatter is not a dict in %s", skill_path)
        return None

    name = frontmatter.get("name", "")
    if not name:
        logger.warning("Skill missing 'name' in %s", skill_path)
        return None

    requires = frontmatter.get("requires", {})
    requires_env = requires.get("env", []) if isinstance(requires, dict) else []

    return Skill(
        name=name,
        description=frontmatter.get("description", ""),
        tools=frontmatter.get("tools", []),
        requires_env=requires_env,
        instructions=match.group(2).strip(),
        path=str(skill_path),
        enabled=frontmatter.get("enabled", True),
    )


def discover_skills(skills_dir: Optional[str | Path] = None) -> list[Skill]:
    """Scan the skills directory for SKILL.md files.

    Each subdirectory containing a SKILL.md is treated as a skill.

    Args:
        skills_dir: Path to skills directory. Defaults to rafi_assistant/skills/.

    Returns:
        List of parsed Skill objects.
    """
    root = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
    skills: list[Skill] = []

    if not root.is_dir():
        logger.info("Skills directory not found: %s", root)
        return skills

    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        skill = parse_skill_file(skill_file)
        if skill:
            skills.append(skill)
            logger.debug("Discovered skill: %s (%d tools)", skill.name, len(skill.tools))

    logger.info("Discovered %d skills in %s", len(skills), root)
    return skills


def filter_eligible(skills: list[Skill]) -> list[Skill]:
    """Filter skills to only those whose requirements are met.

    Checks:
    - Skill is enabled
    - All required environment variables are set

    Args:
        skills: List of discovered skills.

    Returns:
        List of eligible skills.
    """
    ineligibility_reasons = get_ineligibility_reasons(skills)
    eligible = [skill for skill in skills if skill.name not in ineligibility_reasons]

    logger.info(
        "Eligible skills: %d/%d",
        len(eligible), len(skills),
    )
    return eligible


def get_ineligibility_reasons(skills: list[Skill]) -> dict[str, dict[str, Any]]:
    """Return ineligibility reasons for each discovered skill.

    Args:
        skills: List of discovered skills.

    Returns:
        Mapping of skill name -> reason payload.
        Current reason keys:
        - disabled: bool
        - missing_env: list[str]
    """
    reasons: dict[str, dict[str, Any]] = {}

    for skill in skills:
        skill_reasons: dict[str, Any] = {}

        if not skill.enabled:
            skill_reasons["disabled"] = True

        missing_env = [
            var for var in skill.requires_env
            if not os.environ.get(var)
        ]
        if missing_env:
            skill_reasons["missing_env"] = missing_env

        if skill_reasons:
            reasons[skill.name] = skill_reasons

    return reasons


def build_skill_prompt(skills: list[Skill]) -> str:
    """Format eligible skills into a system prompt section.

    Generates instruction text that tells the LLM about available
    skills and how to use them.

    Args:
        skills: List of eligible skills.

    Returns:
        Formatted prompt string (empty if no skills).
    """
    if not skills:
        return ""

    lines = ["## Available Skills\n"]

    for skill in skills:
        lines.append(f"### {skill.name}")
        if skill.description:
            lines.append(skill.description)
        if skill.instructions:
            lines.append(skill.instructions)
        lines.append("")

    return "\n".join(lines)


def get_tool_names_for_skills(skills: list[Skill]) -> set[str]:
    """Get the set of tool names provided by eligible skills.

    Args:
        skills: List of eligible skills.

    Returns:
        Set of tool function names.
    """
    names: set[str] = set()
    for skill in skills:
        names.update(skill.tools)
    return names


def build_startup_validation_report(
    discovered_skills: list[Skill],
    eligible_skills: list[Skill],
    ineligibility_reasons: dict[str, dict[str, Any]],
    exposed_tools: list[str],
) -> str:
    """Build a concise startup report for skills, env gates, and exposed tools.

    Args:
        discovered_skills: All discovered skills.
        eligible_skills: Skills that passed env/enablement checks.
        ineligibility_reasons: Per-skill ineligibility details.
        exposed_tools: Tool names currently exposed to the LLM.

    Returns:
        Multiline report string for startup logs.
    """
    discovered_names = sorted(skill.name for skill in discovered_skills)
    enabled_names = sorted(skill.name for skill in eligible_skills)
    ineligible_names = sorted(ineligibility_reasons.keys())

    missing_env_by_skill: dict[str, list[str]] = {}
    missing_env_flat: set[str] = set()
    for skill_name, reasons in ineligibility_reasons.items():
        missing_env = sorted(reasons.get("missing_env", []))
        if missing_env:
            missing_env_by_skill[skill_name] = missing_env
            missing_env_flat.update(missing_env)

    lines = [
        "--- Startup Validation Report ---",
        f"Skills discovered ({len(discovered_names)}): {', '.join(discovered_names) if discovered_names else 'none'}",
        f"Skills enabled ({len(enabled_names)}): {', '.join(enabled_names) if enabled_names else 'none'}",
        f"Skills ineligible ({len(ineligible_names)}): {', '.join(ineligible_names) if ineligible_names else 'none'}",
    ]

    if missing_env_by_skill:
        lines.append(
            f"Missing env vars ({len(missing_env_flat)}): {', '.join(sorted(missing_env_flat))}"
        )
        for skill_name in sorted(missing_env_by_skill):
            lines.append(
                f"  - {skill_name}: {', '.join(missing_env_by_skill[skill_name])}"
            )
    else:
        lines.append("Missing env vars (0): none")

    lines.append(
        f"Exposed tools ({len(exposed_tools)}): {', '.join(sorted(exposed_tools)) if exposed_tools else 'none'}"
    )
    lines.append("---------------------------------")

    return "\n".join(lines)
