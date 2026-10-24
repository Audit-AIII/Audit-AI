"""Intent-lock: text the writer marked as must-keep (a price, a date, a product name, a call to
action) must survive every suggested rewrite (DESIGN.md §21 D/§22: "protected spans cannot change
in a suggestion").

Semantics follow the frontend (audit-ai-final/frontend/lib/additions/locks.ts): a lock is an exact
phrase, matched case-sensitively as a substring. This module adds one strictness the frontend's
"still present" test lacks: a phrase that occurs n times in the original must still occur at
least n times, so removing one of two "₹2,499" is caught.

Enforcement is deterministic. A prompt instruction is never relied on:
* ``ClaimCorrector.correct`` and ``ClaimSoftener.soften`` take ``locked_phrases`` and refuse any
  proposal that would remove locked text (a correction becomes NEEDS_HUMAN_REVIEW with issue
  ``intent_lock``; a softening returns None);
* ``intent_lock_violations`` / ``check_replacement`` are for the backend to enforce the same rule
  server-side on anything it stores (suggestions, user edits, new versions). See
  HANDOFF_STEPS_6_8.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

MAX_LOCKS = 50
MAX_LOCK_CHARS = 200


class IntentLockError(ValueError):
    """The locks are malformed (not a list of non-blank strings within the limits)."""


class IntentLockViolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phrase: str = Field(max_length=MAX_LOCK_CHARS)
    occurrences_before: int = Field(ge=1)
    occurrences_after: int = Field(ge=0)


def validate_locks(locks: Iterable[str] | None) -> list[str]:
    """The locks, deduplicated in order. Raises IntentLockError for malformed input; never drops a
    lock silently (a dropped lock would let protected text change)."""
    if locks is None:
        return []
    if isinstance(locks, str) or not isinstance(locks, Iterable):
        raise IntentLockError("locked phrases must be a list of strings")
    clean: list[str] = []
    for lock in locks:
        if not isinstance(lock, str) or not lock.strip():
            raise IntentLockError("every locked phrase must be non-blank text")
        if len(lock) > MAX_LOCK_CHARS:
            raise IntentLockError(f"a locked phrase may be at most {MAX_LOCK_CHARS} characters")
        if lock not in clean:
            clean.append(lock)
    if len(clean) > MAX_LOCKS:
        raise IntentLockError(f"at most {MAX_LOCKS} locked phrases")
    return clean


def intent_lock_violations(
    original: str, revised: str, locks: Sequence[str] | None
) -> list[IntentLockViolation]:
    """Locked phrases that ``revised`` keeps fewer times than ``original`` (empty: allowed)."""
    found = []
    for phrase in validate_locks(locks):
        before = original.count(phrase)
        after = revised.count(phrase)
        if before and after < before:
            found.append(
                IntentLockViolation(
                    phrase=phrase, occurrences_before=before, occurrences_after=after
                )
            )
    return found


def check_replacement(
    text: str, start: int, end: int, replacement: str, locks: Sequence[str] | None
) -> list[IntentLockViolation]:
    """Violations if ``text[start:end]`` were replaced by ``replacement`` (the whole text is
    compared, so a lock that straddles the edit boundary is caught too)."""
    if not 0 <= start <= end <= len(text):
        raise ValueError("the replaced range must lie inside the text")
    return intent_lock_violations(text, text[:start] + replacement + text[end:], locks)
