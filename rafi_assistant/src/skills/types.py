"""Skill type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Skill:
    """A discovered skill with parsed metadata."""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    instructions: str = ""
    path: str = ""
    enabled: bool = True

    @property
    def tool_names(self) -> list[str]:
        """Return the tool names this skill provides."""
        return self.tools
