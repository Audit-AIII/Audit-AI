"""Keeps credentials out of logs and errors, and cleans model-written text before display.

See SECURITY.md for the threat model and what each control does and does not cover.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata

_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"sk-or-[A-Za-z0-9_-]{8,}"),  # OpenRouter key format
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
]
REDACTED = "[REDACTED]"

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(secret: str) -> None:
    """Adds a configured credential to the set every RedactingFilter removes. Short values are
    ignored: redacting a 3-character string would mangle ordinary log text."""
    if secret and len(secret) >= 8:
        with _lock:
            _secrets.add(secret)


def redact(text: str, *secrets: str) -> str:
    """``text`` with every registered or given secret and every known credential pattern replaced."""
    with _lock:
        known = _secrets | {s for s in secrets if s}
    for secret in sorted(known, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.re.groups else "") + REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites each record's final message so credentials never reach a handler."""

    def __init__(self, *secrets: str) -> None:
        super().__init__()
        for secret in secrets:
            register_secret(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def install_redaction(target: logging.Logger | logging.Handler) -> None:
    """Attaches one RedactingFilter to a logger or handler (idempotent).

    A logger filter only sees records created on that logger; attach to the application's
    handlers to cover every logger, including third-party ones.
    """
    if not any(isinstance(f, RedactingFilter) for f in target.filters):
        target.addFilter(RedactingFilter())


# Bidirectional overrides and isolates can make displayed text read differently from what it
# is ("Trojan Source"); zero-width characters can hide text. Neither belongs in a rationale.
_INVISIBLE = {"​", "‌", "‍", "⁠", "﻿"}
_BIDI = {chr(c) for c in range(0x202A, 0x202F)} | {chr(c) for c in range(0x2066, 0x206A)}


def clean_display_text(text: str, max_length: int) -> str | None:
    """Model-written text made safe to show as plain text: control, bidi-override and zero-width
    characters removed, whitespace runs collapsed, truncated. None if nothing is left.

    Never use this on content or evidence: their offsets must stay exact. It is for text the
    model wrote (rationales, reasons), which is displayed but never cited.
    """
    kept = (
        " " if ch in "\t\n\r" else ch
        for ch in text
        if ch not in _INVISIBLE and ch not in _BIDI and (ch in "\t\n\r" or unicodedata.category(ch) != "Cc")
    )
    cleaned = " ".join("".join(kept).split())[:max_length]
    return cleaned or None
