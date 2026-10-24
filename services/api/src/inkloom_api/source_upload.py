"""Turns an uploaded brand source file into plain text, and stores the original bytes outside
any public path (Phase 4 task 3). Three file types only: .txt, .pdf, .docx.

This is this backend's own scope, not the engine's or the frontend's: CONTRACTS.md says "the
engine receives plain text; uploads ... parsing ... are not part of these contracts" - someone
still has to own it, and for brand sources (as opposed to submitted content, which arrives as
plain text already) that owner is this module.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import docx
from fastapi import HTTPException, UploadFile, status
from inkloom_verify.schemas import MAX_REFERENCE_CHARS
from pypdf import PdfReader

from .config import Settings
from .request_text import NUL
from .statuses import SourceFileType

_EXTENSION_TO_TYPE = {".txt": SourceFileType.TXT, ".pdf": SourceFileType.PDF, ".docx": SourceFileType.DOCX}


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def file_type_from_name(filename: str | None) -> SourceFileType:
    suffix = Path(filename or "").suffix.lower()
    file_type = _EXTENSION_TO_TYPE.get(suffix)
    if file_type is None:
        allowed = ", ".join(sorted(e.lstrip(".") for e in _EXTENSION_TO_TYPE))
        raise _bad_request(f"unsupported file type: must be one of {allowed}")
    return file_type


def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Reads at most `max_bytes` + 1 bytes, so an oversized upload is caught without first
    buffering the whole thing (a spoofed Content-Length header is never trusted alone)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise _bad_request(f"file exceeds the {max_bytes // (1024 * 1024)} MB limit")
    return b"".join(chunks)


def extract_text(file_type: SourceFileType, content: bytes) -> str:
    if file_type is SourceFileType.TXT:
        text = _decode_text(content)
    elif file_type is SourceFileType.PDF:
        text = _extract_pdf_text(content)
    else:
        text = _extract_docx_text(content)

    text = text.strip()
    if not text:
        raise _bad_request("no extractable text found in the uploaded file")
    if NUL in text:
        # PostgreSQL text can't store it (request_text.py). In a .txt it usually means UTF-16.
        raise _bad_request("file contains NUL (0x00) characters; save it as UTF-8 text")
    if len(text) > MAX_REFERENCE_CHARS:
        raise _bad_request(f"extracted text exceeds the {MAX_REFERENCE_CHARS:,} character limit")
    return text


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        raise _bad_request("file is not valid UTF-8 text") from None


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as error:  # pypdf raises several distinct error types for a malformed PDF
        raise _bad_request(f"could not read PDF: {type(error).__name__}") from None
    return "\n\n".join(p for p in pages if p)


def _extract_docx_text(content: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(content))
    except Exception as error:  # python-docx raises several distinct error types
        raise _bad_request(f"could not read DOCX: {type(error).__name__}") from None
    return "\n".join(p.text for p in document.paragraphs if p.text)


def store_upload(settings: Settings, organisation_id: uuid.UUID, file_type: SourceFileType, content: bytes) -> str:
    """Saves the raw uploaded bytes under `brand_source_storage_dir`, named by a generated id -
    never the original filename (avoids path traversal and collisions, and the name itself
    could be sensitive). Returns the path, relative to that directory, stored in
    `brand_sources.storage_path` for provenance only; the extracted text in `source_versions` is
    what the engine actually reads."""
    base = Path(settings.brand_source_storage_dir) / str(organisation_id)
    base.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{file_type.value}"
    (base / name).write_bytes(content)
    return f"{organisation_id}/{name}"
