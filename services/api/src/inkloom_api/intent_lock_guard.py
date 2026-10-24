"""Backend enforcement of Intent-lock: the writer's must-keep phrases (a price, a date, a product
name) are never removed by a suggestion this backend offers (DESIGN.md §21 D / §22).

The engine already refuses lock-breaking corrections and softenings when it is given the locks
(inkloom_verify.intent_lock, HANDOFF_STEPS_6_8.md). "The backend never trusts the engine", so the
same deterministic check runs here on every suggestion before it is stored, and again when it is
read - locks can be set after a review ran, and a suggestion that breaks them is then withheld
(never deleted). Semantics are the engine's: exact, case-sensitive phrases, and a phrase that
occurs n times must still occur n times.
"""

from __future__ import annotations

from collections.abc import Sequence

from inkloom_verify.intent_lock import check_replacement


def breaks_locks(text: str, start: int, end: int, replacement: str | None, locks: Sequence[str]) -> bool:
    """True if replacing text[start:end] with `replacement` would remove a locked phrase."""
    if not replacement or not locks or not 0 <= start <= end <= len(text):
        return False
    return bool(check_replacement(text, start, end, replacement, locks))
