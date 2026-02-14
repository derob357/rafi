"""Unit tests for skill discovery, eligibility, and startup reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.skills.loader import (
    build_startup_validation_report,
    discover_skills,
    filter_eligible,
    get_ineligibility_reasons,
    get_tool_names_for_skills,
    parse_skill_file,
)


def _write_skill_file(skill_dir: Path, frontmatter: str, body: str = "# Skill\n") -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return path


def test_parse_skill_file_valid() -> None:
    root = Path(__file__).parent
    skill_path = root / "_tmp_parse_valid_SKILL.md"
    skill_path.write_text(
        """---
name: sample
description: Sample skill
tools:
  - tool_a
requires:
  env:
    - SAMPLE_KEY
enabled: true
---

# Sample
Use tool_a.
""",
        encoding="utf-8",
    )
    try:
        skill = parse_skill_file(skill_path)
        assert skill is not None
        assert skill.name == "sample"
        assert skill.tools == ["tool_a"]
        assert skill.requires_env == ["SAMPLE_KEY"]
        assert skill.enabled is True
    finally:
        skill_path.unlink(missing_ok=True)


def test_parse_skill_file_invalid_yaml(tmp_path: Path) -> None:
    skill_file = tmp_path / "bad" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        """---
name: bad
tools: [x
---

invalid
""",
        encoding="utf-8",
    )
    assert parse_skill_file(skill_file) is None


def test_discover_skills_ignores_non_skill_folders(tmp_path: Path) -> None:
    _write_skill_file(
        tmp_path / "calendar",
        "name: calendar\ndescription: Calendar\ntools:\n  - read_calendar\nrequires:\n  env: []",
    )
    (tmp_path / "notes").mkdir(parents=True, exist_ok=True)
    _write_skill_file(
        tmp_path / "weather",
        "name: weather\ndescription: Weather\ntools:\n  - get_weather\nrequires:\n  env:\n    - WEATHER_API_KEY",
    )

    discovered = discover_skills(tmp_path)
    names = sorted(skill.name for skill in discovered)

    assert names == ["calendar", "weather"]


def test_ineligibility_reasons_reports_disabled_and_missing_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_skill_file(
        tmp_path / "enabled_missing_env",
        "name: enabled_missing_env\ndescription: x\ntools:\n  - t1\nrequires:\n  env:\n    - MISSING_ENV",
    )
    _write_skill_file(
        tmp_path / "disabled_skill",
        "name: disabled_skill\ndescription: x\ntools:\n  - t2\nenabled: false\nrequires:\n  env: []",
    )

    monkeypatch.delenv("MISSING_ENV", raising=False)
    skills = discover_skills(tmp_path)
    reasons = get_ineligibility_reasons(skills)

    assert "enabled_missing_env" in reasons
    assert reasons["enabled_missing_env"]["missing_env"] == ["MISSING_ENV"]
    assert "disabled_skill" in reasons
    assert reasons["disabled_skill"]["disabled"] is True


def test_filter_eligible_respects_env_requirements(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_skill_file(
        tmp_path / "alpha",
        "name: alpha\ndescription: x\ntools:\n  - a\nrequires:\n  env:\n    - ALPHA_KEY",
    )
    _write_skill_file(
        tmp_path / "beta",
        "name: beta\ndescription: x\ntools:\n  - b\nrequires:\n  env: []",
    )

    monkeypatch.delenv("ALPHA_KEY", raising=False)
    eligible = filter_eligible(discover_skills(tmp_path))
    assert sorted(skill.name for skill in eligible) == ["beta"]

    monkeypatch.setenv("ALPHA_KEY", "set")
    eligible = filter_eligible(discover_skills(tmp_path))
    assert sorted(skill.name for skill in eligible) == ["alpha", "beta"]


def test_get_tool_names_for_skills_deduplicates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("K1", "yes")
    _write_skill_file(
        tmp_path / "s1",
        "name: s1\ndescription: x\ntools:\n  - t_common\n  - t_1\nrequires:\n  env:\n    - K1",
    )
    _write_skill_file(
        tmp_path / "s2",
        "name: s2\ndescription: x\ntools:\n  - t_common\n  - t_2\nrequires:\n  env: []",
    )

    tools = get_tool_names_for_skills(filter_eligible(discover_skills(tmp_path)))
    assert tools == {"t_common", "t_1", "t_2"}


def test_build_startup_validation_report_contains_expected_sections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NEEDS_KEY", raising=False)
    _write_skill_file(
        tmp_path / "eligible",
        "name: eligible\ndescription: x\ntools:\n  - ok_tool\nrequires:\n  env: []",
    )
    _write_skill_file(
        tmp_path / "ineligible",
        "name: ineligible\ndescription: x\ntools:\n  - bad_tool\nrequires:\n  env:\n    - NEEDS_KEY",
    )

    discovered = discover_skills(tmp_path)
    eligible = filter_eligible(discovered)
    reasons = get_ineligibility_reasons(discovered)

    report = build_startup_validation_report(
        discovered_skills=discovered,
        eligible_skills=eligible,
        ineligibility_reasons=reasons,
        exposed_tools=["ok_tool"],
    )

    assert "Startup Validation Report" in report
    assert "Skills discovered (2)" in report
    assert "Skills enabled (1)" in report
    assert "Skills ineligible (1)" in report
    assert "Missing env vars (1): NEEDS_KEY" in report
    assert "ineligible: NEEDS_KEY" in report
    assert "Exposed tools (1): ok_tool" in report
