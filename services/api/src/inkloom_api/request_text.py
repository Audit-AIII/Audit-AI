"""Free-text request fields that end up in a PostgreSQL text column.

PostgreSQL text cannot hold a NUL (0x00) character: inserting one raises a DataError, which
surfaced as a 500 for any title, name, note or draft containing it. `StoredText` refuses it at
validation instead, so the caller gets the standard 422 naming the field (never its value).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator

NUL = "\x00"


def _no_nul(value: str) -> str:
    if NUL in value:
        raise ValueError("must not contain NUL (0x00) characters")
    return value


StoredText = Annotated[str, AfterValidator(_no_nul)]


def contains_nul(value: object) -> bool:
    """True if any string inside a JSON-like value (keys included) holds a NUL - for request
    bodies stored as JSONB, which PostgreSQL also refuses to hold it in."""
    if isinstance(value, str):
        return NUL in value
    if isinstance(value, dict):
        return any(contains_nul(k) or contains_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_nul(v) for v in value)
    return False
