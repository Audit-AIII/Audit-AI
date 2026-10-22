"""Keeps credentials out of logs and error messages."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"sk-or-[A-Za-z0-9_-]{8,}"),  # OpenRouter key format
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
]
REDACTED = "[REDACTED]"


def redact(text: str, *secrets: str) -> str:
    """``text`` with every given secret and every known credential pattern replaced."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.re.groups else "") + REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites each record's final message so credentials never reach a handler."""

    def __init__(self, *secrets: str) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), *self._secrets)
        record.args = None
        return True
