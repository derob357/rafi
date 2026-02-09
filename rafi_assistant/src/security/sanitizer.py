"""Input sanitization functions for all text inputs.

Central module for stripping dangerous content, detecting prompt injection,
and sanitizing email HTML bodies before passing to the LLM.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum lengths for different input types
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
MAX_VOICE_TRANSCRIPTION_LENGTH = 10000
MAX_EMAIL_BODY_LENGTH = 2000
MAX_DEFAULT_LENGTH = 4096

# Known prompt injection patterns (case-insensitive)
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(the\s+)?(rules|above)", re.IGNORECASE),
    re.compile(r"ignore\s+all\s+safety", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|your\s+instructions|everything)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|DAN)\b", re.IGNORECASE),
    re.compile(r"\bDAN\b.*\bDo\s+Anything\s+Now\b", re.IGNORECASE),
    re.compile(r"new\s+(instructions?|system\s+prompt|task)\s*(?::|is\s+to)", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"ASSISTANT\s*:", re.IGNORECASE),
    re.compile(r"###\s*ASSISTANT\s*###", re.IGNORECASE),
    re.compile(r"\bsystem\s*prompt", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?(instructions|system)", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+(are|were|have)", re.IGNORECASE),
    re.compile(r"pretend\s+(that\s+)?you\s+(are|were)", re.IGNORECASE),
    re.compile(r"roleplay\s+as", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
    re.compile(r"developer\s+mode\s+(enabled|on|activated)", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"<<SYS>>", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>", re.IGNORECASE),
    re.compile(r"BEGIN\s+INJECTION", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your\s+)?", re.IGNORECASE),
    re.compile(r"bypass\s+(your\s+)?(content\s+)?filter", re.IGNORECASE),
    re.compile(r"Human:\s*Ignore", re.IGNORECASE),
    re.compile(r"```system\b", re.IGNORECASE),
]

# Zero-width and invisible characters to strip
ZERO_WIDTH_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    r"\u2060\u2061\u2062\u2063\u2064\u2066\u2067\u2068\u2069\ufeff\ufffe]"
)

# Control characters (except common whitespace: tab, newline, carriage return)
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# HTML tag pattern
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# HTML style and script blocks
HTML_BLOCK_PATTERN = re.compile(
    r"<(style|script|head)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_text(
    text: Optional[str],
    max_length: int = MAX_DEFAULT_LENGTH,
) -> str:
    """Sanitize arbitrary text input by stripping dangerous content.

    Removes HTML tags, control characters, zero-width characters,
    and truncates to the specified maximum length.

    Args:
        text: The input text to sanitize. None returns empty string.
        max_length: Maximum allowed length after sanitization.

    Returns:
        Sanitized text string, guaranteed non-None and within length limits.
    """
    if text is None:
        return ""

    if not isinstance(text, str):
        logger.warning("sanitize_text received non-string input: %s", type(text).__name__)
        text = str(text)

    # Strip zero-width and invisible characters
    result = ZERO_WIDTH_CHARS.sub("", text)

    # Strip control characters (preserve tabs, newlines)
    result = CONTROL_CHARS.sub("", result)

    # Remove style, script, and head blocks entirely
    result = HTML_BLOCK_PATTERN.sub("", result)

    # Strip HTML tags
    result = HTML_TAG_PATTERN.sub("", result)

    # Decode HTML entities
    result = html.unescape(result)

    # Normalize whitespace (collapse multiple spaces/newlines)
    result = re.sub(r" {2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Trim leading and trailing whitespace
    result = result.strip()

    # Truncate to max length
    if len(result) > max_length:
        result = result[:max_length]
        logger.warning(
            "Text truncated from %d to %d characters",
            len(text),
            max_length,
        )

    return result


def sanitize_telegram_message(text: Optional[str]) -> str:
    """Sanitize a Telegram message using the standard length limit.

    Args:
        text: The raw Telegram message text.

    Returns:
        Sanitized text truncated to MAX_TELEGRAM_MESSAGE_LENGTH.
    """
    return sanitize_text(text, max_length=MAX_TELEGRAM_MESSAGE_LENGTH)


def sanitize_voice_transcript(text: Optional[str]) -> str:
    """Sanitize a voice transcription using the extended length limit.

    Args:
        text: The raw voice transcription text.

    Returns:
        Sanitized text truncated to MAX_VOICE_TRANSCRIPTION_LENGTH.
    """
    return sanitize_text(text, max_length=MAX_VOICE_TRANSCRIPTION_LENGTH)


def detect_prompt_injection(text: Optional[str]) -> bool:
    """Check if text contains known prompt injection patterns.

    Strips zero-width characters and normalizes unicode before
    checking against known injection patterns.

    Args:
        text: The text to check. None returns False.

    Returns:
        True if a prompt injection pattern is detected, False otherwise.
    """
    if not text:
        return False

    # Strip zero-width and invisible characters before checking
    cleaned = ZERO_WIDTH_CHARS.sub("", text)
    # Normalize unicode (e.g., combining diacriticals, homoglyphs)
    cleaned = unicodedata.normalize("NFKD", cleaned)
    # Strip combining characters (diacritical marks)
    cleaned = "".join(c for c in cleaned if not unicodedata.combining(c))

    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            logger.warning(
                "Prompt injection detected matching pattern: %s",
                pattern.pattern,
            )
            return True

    return False


def sanitize_email_body(html_content: Optional[str]) -> str:
    """Sanitize an email body from HTML to plain text.

    Strips HTML tags, script/style blocks, decodes entities,
    and truncates to the email body length limit.

    Args:
        html_content: Raw HTML email body. None returns empty string.

    Returns:
        Plain text version of the email body, truncated to MAX_EMAIL_BODY_LENGTH.
    """
    if html_content is None:
        return ""

    if not isinstance(html_content, str):
        logger.warning(
            "sanitize_email_body received non-string input: %s",
            type(html_content).__name__,
        )
        html_content = str(html_content)

    # Remove style, script, and head blocks entirely
    result = HTML_BLOCK_PATTERN.sub("", html_content)

    # Replace <br> and <p> with newlines for readability
    result = re.sub(r"<br\s*/?>", "\n", result, flags=re.IGNORECASE)
    result = re.sub(r"</p>", "\n", result, flags=re.IGNORECASE)
    result = re.sub(r"<p[^>]*>", "", result, flags=re.IGNORECASE)

    # Replace list items with bullets
    result = re.sub(r"<li[^>]*>", "- ", result, flags=re.IGNORECASE)

    # Strip remaining HTML tags
    result = HTML_TAG_PATTERN.sub("", result)

    # Decode HTML entities
    result = html.unescape(result)

    # Strip zero-width characters
    result = ZERO_WIDTH_CHARS.sub("", result)

    # Strip control characters
    result = CONTROL_CHARS.sub("", result)

    # Normalize whitespace
    result = re.sub(r" {2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = result.strip()

    # Truncate
    if len(result) > MAX_EMAIL_BODY_LENGTH:
        result = result[:MAX_EMAIL_BODY_LENGTH]
        logger.info("Email body truncated to %d characters", MAX_EMAIL_BODY_LENGTH)

    return result


def wrap_user_input(text: str) -> str:
    """Wrap user input in clear delimiters for the LLM prompt.

    Provides boundary markers to help the LLM distinguish user input
    from system instructions, as a defense against prompt injection.

    Args:
        text: The sanitized user input text.

    Returns:
        Text wrapped in delimiter markers.
    """
    return f"[BEGIN USER MESSAGE]\n{text}\n[END USER MESSAGE]"
