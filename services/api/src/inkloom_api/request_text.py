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
