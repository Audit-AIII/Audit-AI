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


def has_hidden_characters(text: str) -> bool:
    """True if ``text`` holds a control character (line breaks included), a bidi override or
    isolate, or a zero-width character. Engine-written fields that are shown on one line (a
    claim's rewording, a correction's replacement) must not: they could reorder what a reviewer
    sees, hide words, or start a Markdown block."""
    return any(ch in _INVISIBLE or ch in _BIDI or unicodedata.category(ch) == "Cc" for ch in text)


def clean_display_text(text: str, max_length: int) -> str | None:
    """Model-written text made safe to show as plain text: control, bidi-override and zero-width
    characters removed, whitespace runs collapsed, truncated. None if nothing is left.

    Never use this on content or evidence: their offsets must stay exact. It is for text the
    model wrote (rationales, reasons), which is displayed but never cited.
    """
    kept = (
        " " if ch in "\t\n\r" else ch
        for ch in text
        if ch not in _INVISIBLE
        and ch not in _BIDI
        and (ch in "\t\n\r" or unicodedata.category(ch) != "Cc")
    )
    cleaned = " ".join("".join(kept).split())[:max_length]
    return cleaned or None


# A model told by injected text to "print your instructions" would write them into the only free
# text it returns. The prompts are not secret (they are in the repository), but repeating them is
# a sign the model followed the content, and the text is shown to people. 60 characters is about
# one line of a prompt: long enough that a rationale quoting a rule word ("NOT_ENOUGH_EVIDENCE",
# "untrusted data") never matches.
PROMPT_ECHO_CHARS = 60
WITHHELD_ECHO = "[withheld: the model's text repeated its instructions]"


def repeats_instructions(text: str, instructions: str, window: int = PROMPT_ECHO_CHARS) -> bool:
    """Whether ``text`` contains any ``window``-character run of ``instructions`` (case and
    whitespace ignored)."""
    haystack = " ".join(text.split()).casefold()
    needle = " ".join(instructions.split()).casefold()
    if len(haystack) < window or len(needle) < window:
        return False
    return any(needle[i : i + window] in haystack for i in range(len(needle) - window + 1))


def model_text_for_display(text: str, max_length: int, instructions: str) -> str | None:
    """Model-written prose (a rationale, a reason) as it may be shown: ``clean_display_text``,
    credentials redacted, and replaced by ``WITHHELD_ECHO`` if it repeats ``instructions``."""
    cleaned = clean_display_text(text, max_length)
    if cleaned is None:
        return None
    if repeats_instructions(cleaned, instructions):
        return WITHHELD_ECHO
    return redact(cleaned)[:max_length]


# Text aimed at the model rather than at readers of a fact sheet or of marketing copy. Used by the
# citation guard (a quote from such a sentence is not evidence) and the extractor (such a sentence
# is not a claim). Deliberately narrow, because a false match discards real evidence or a real
# claim: measured (PROMPTS.md Phase 6) on every reference sentence, content sentence and claim in
# eval/data, it flags only the planted injections and no gold evidence quote or labelled claim;
# tests/test_prompt_security.py also holds legitimate wording ("System: Android 14", "Note to
# reviewers: ...", "Never ignore the safety instructions") that must pass. It is one check among
# several, not a prompt-injection detector: an instruction worded as a plain fact ("Lumen Pods are
# waterproof.") passes it.
_INSTRUCTION = re.compile(
    r"\b(?:SUPPORTED|CONTRADICTED|NOT_ENOUGH_EVIDENCE)\b"  # the verdict names, as the prompts write them
    r"|(?i:(?<!not )(?<!never )(?<!n't )\b(?:ignore|disregard|override|forget)\b[^.\n]{0,60}"
    r"\b(?:instructions?|rules?|prompts?|guidelines?|fact sheets?|evidence|passages?)\b)"
    r"|(?i:\bsystem\s+prompts?\b|\bdeveloper\s+(?:message|instructions?)\b|\b(?:previous|prior|above)\s+instructions\b)"
    r"|(?i:\b(?:note|message|instructions?)\s+(?:to|for)\s+(?:any\s+|the\s+|all\s+)?"
    r"(?:AI|LLMs?|chatbots?|(?:language\s+)?models?|assistants?|verifiers?)\b)"
    r"|(?i:\b(?:mark|label|treat|classify)\b[^.\n]{0,40}\b(?:as\s+)?(?:supported|verified|true|pre-verified)\b)"
    # Scripted answers for a model (EVAL.md Phase 6, regression REG-012: the v1-032 trap sentence
    # 'If asked for a quote, use: "..."' was accepted as evidence). Needs a verb that tells the
    # reader what to answer, so "If asked for a quote, our sales team responds" is not matched.
    r"|(?i:\b(?:if|when)\s+(?:you\s+are\s+|you're\s+)?asked\b[^.\n]{0,40}\b(?:use|cite|answer|say|reply)\b)"
)


def instruction_like(text: str) -> bool:
    """Whether ``text`` addresses an AI, names a verdict, or tells the reader to ignore rules."""
    return _INSTRUCTION.search(text) is not None
