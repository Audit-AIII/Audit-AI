"""Loads versioned prompt files: ``prompts/<version>.txt``, e.g. ``verify-claim-v1.txt``.

The file name is the version id recorded in reports, so there is nothing to keep in sync. Rules:

* A prompt is loaded by component and **exact** version. There is no "latest" and no fallback:
  a missing file, or a version belonging to another component, is a ``PromptNotFoundError``.
* Released versions are listed with their SHA-256 in ``prompts.lock.json``. A released prompt is
  never edited; the loader refuses one whose text no longer matches (``PromptIntegrityError``).
* Line endings are normalised to LF and the file's final newline is dropped, so a Windows
  checkout sends the model exactly the released text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
LOCK_FILE = PROMPT_DIR / "prompts.lock.json"

# Component -> the version-id prefix its prompt files use.
COMPONENTS = {
    "extraction": "extract-claims",
    "verification": "verify-claim",
    "correction": "correct-claim",
    "softening": "soften-claim",
}


class PromptNotFoundError(LookupError):
    """The requested prompt version does not exist for that component."""


class PromptIntegrityError(RuntimeError):
    """A released prompt's text no longer matches prompts.lock.json: it was edited in place."""


@dataclass(frozen=True)
class LoadedPrompt:
    component: str
    version: str
    text: str
    sha256: str
    released: bool


def _normalise(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    return text[:-1] if text.endswith("\n") else text


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def released_versions() -> dict[str, dict[str, str]]:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))["released"]


def available_versions(component: str) -> list[str]:
    prefix = _prefix(component)
    return sorted(p.stem for p in PROMPT_DIR.glob(f"{prefix}-v*.txt"))


def _prefix(component: str) -> str:
    if component not in COMPONENTS:
        raise PromptNotFoundError(
            f"unknown prompt component {component!r}; expected one of {sorted(COMPONENTS)}"
        )
    return COMPONENTS[component]


def load_prompt(component: str, version: str) -> LoadedPrompt:
    """The prompt text of exactly ``version`` for ``component``. Never a different version."""
    prefix = _prefix(component)
    if not re.fullmatch(rf"{re.escape(prefix)}-v[0-9]+", version):
        raise PromptNotFoundError(
            f"{version!r} is not a {component} prompt version (expected {prefix}-v<number>)"
        )
    path = PROMPT_DIR / f"{version}.txt"
    if not path.is_file():
        raise PromptNotFoundError(
            f"prompt {version!r} not found at {path.name}; available {component} versions: "
            f"{', '.join(available_versions(component)) or 'none'}"
        )
    text = _normalise(path.read_text(encoding="utf-8"))
    if not text.strip():
        raise PromptNotFoundError(f"prompt {version!r} is empty")
    digest = sha256_of(text)
    entry = released_versions().get(version)
    if entry is not None:
        if entry["component"] != component:
            raise PromptIntegrityError(
                f"prompts.lock.json lists {version!r} under {entry['component']!r}, not {component!r}"
            )
        if entry["sha256"] != digest:
            raise PromptIntegrityError(
                f"released prompt {version!r} was edited in place (its text no longer matches prompts.lock.json); "
                "restore it and put the new wording in a new version"
            )
    return LoadedPrompt(
        component=component, version=version, text=text, sha256=digest, released=entry is not None
    )
