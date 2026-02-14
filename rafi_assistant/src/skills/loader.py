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
    eligible: list[Skill] = []

    for skill in skills:
        if not skill.enabled:
            logger.debug("Skill %s is disabled, skipping", skill.name)
            continue

        missing_env = [
            var for var in skill.requires_env
            if not os.environ.get(var)
        ]

        if missing_env:
            logger.debug(
                "Skill %s missing env vars: %s, skipping",
                skill.name, missing_env,
            )
            continue

        eligible.append(skill)

    logger.info(
        "Eligible skills: %d/%d",
        len(eligible), len(skills),
    )
    return eligible


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
