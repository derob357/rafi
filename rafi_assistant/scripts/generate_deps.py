#!/usr/bin/env python3
"""Generate DEPENDENCIES.md from requirements.txt."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Map of package names to their purpose descriptions
PACKAGE_PURPOSES = {
    "python-telegram-bot": "Telegram bot framework (async)",
    "fastapi": "ASGI web framework for Twilio webhooks",
    "uvicorn": "ASGI server for FastAPI",
    "twilio": "Twilio voice call API client",
    "elevenlabs": "ElevenLabs Conversational AI + TTS",
    "openai": "OpenAI LLM and embedding API client",
    "anthropic": "Anthropic Claude LLM API client",
    "deepgram-sdk": "Deepgram speech-to-text API client",
    "google-api-python-client": "Google Calendar and Gmail API client",
    "google-auth-oauthlib": "Google OAuth 2.0 authentication",
    "google-auth-httplib2": "Google Auth HTTP transport",
    "supabase": "Supabase PostgreSQL + pgvector client",
    "httpx": "Async HTTP client",
    "apscheduler": "Task scheduler for briefings and reminders",
    "pyyaml": "YAML config file parsing",
    "pydantic": "Data validation and config models",
    "cryptography": "Fernet encryption for OAuth tokens",
    "python-json-logger": "Structured JSON log formatting",
    "pytest": "Test framework",
    "pytest-asyncio": "Async test support for pytest",
    "pytest-cov": "Test coverage reporting",
    "pytest-mock": "Mock fixtures for pytest",
    "mypy": "Static type checker",
}


def parse_requirements(req_path: Path) -> list[tuple[str, str]]:
    """Parse requirements.txt and return (package, version) tuples."""
    packages = []
    if not req_path.exists():
        print(f"Error: {req_path} not found", file=sys.stderr)
        sys.exit(1)

    for line in req_path.read_text().strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove extras like [httpx]
        clean = re.sub(r"\[.*?\]", "", line)
        # Split on ==
        match = re.match(r"^([a-zA-Z0-9_-]+)==(.+)$", clean)
        if match:
            packages.append((match.group(1), match.group(2)))
        else:
            # Handle packages without pinned version
            name_match = re.match(r"^([a-zA-Z0-9_-]+)", clean)
            if name_match:
                packages.append((name_match.group(1), "latest"))

    return packages


def generate_markdown(packages: list[tuple[str, str]]) -> str:
    """Generate the DEPENDENCIES.md content."""
    lines = [
        "# Dependencies",
        "",
        "Auto-generated from requirements.txt. Do not edit manually.",
        "",
        "| Package | Version | Purpose |",
        "|---------|---------|---------|",
    ]

    for name, version in packages:
        purpose = PACKAGE_PURPOSES.get(name, "")
        lines.append(f"| {name} | {version} | {purpose} |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """Main entry point."""
    project_root = Path(__file__).parent.parent
    req_path = project_root / "requirements.txt"
    output_path = project_root / "DEPENDENCIES.md"

    packages = parse_requirements(req_path)
    markdown = generate_markdown(packages)

    output_path.write_text(markdown)
    print(f"Generated {output_path} with {len(packages)} packages")


if __name__ == "__main__":
    main()
