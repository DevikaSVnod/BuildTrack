"""Read files from Azure Blob (or generate placeholders for legacy /uploads paths)."""
from __future__ import annotations

import logging
import mimetypes
import os
import time
import urllib.parse
from threading import Lock
from typing import Optional

from app.core.config import settings
from app.storage.document_blob import generate_document_bytes, is_blob_url

logger = logging.getLogger(__name__)

_blob_service = None
_blob_lock = Lock()

# Short in-process cache so opening the same preview twice is instant.
_FILE_CACHE_TTL = 180.0
_file_bytes_cache: dict[str, tuple[float, bytes, str]] = {}
_file_cache_lock = Lock()


def _guess_content_type(filename: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


def parse_blob_url(file_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(file_url)
    parts = parsed.path.lstrip("/").split("/", 1)
    if len(parts) < 2:
        raise ValueError(f"Invalid blob URL: {file_url}")
    container = parts[0]
    blob_name = urllib.parse.unquote(parts[1])
    return container, blob_name


def _get_blob_service():
    global _blob_service
    if _blob_service is not None:
        return _blob_service
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("Azure Storage is not configured")
    with _blob_lock:
        if _blob_service is not None:
            return _blob_service
        from azure.storage.blob import BlobServiceClient

        _blob_service = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        return _blob_service


def fetch_blob_bytes(file_url: str) -> tuple[bytes, str]:
    now = time.time()
    with _file_cache_lock:
        cached = _file_bytes_cache.get(file_url)
        if cached and now - cached[0] < _FILE_CACHE_TTL:
            return cached[1], cached[2]

    container, blob_name = parse_blob_url(file_url)
    client = _get_blob_service()
    blob = client.get_blob_client(container=container, blob=blob_name)
    props = blob.get_blob_properties()
    content_type = (
        props.content_settings.content_type if props.content_settings else None
    ) or _guess_content_type(blob_name)
    # Some uploads may have incorrect content-type metadata; for vision calls we must
    # provide an image/* MIME when the blob name indicates an image.
    guessed = _guess_content_type(blob_name)
    if guessed and guessed.startswith("image/"):
        content_type = guessed
    content = blob.download_blob().readall()

    with _file_cache_lock:
        _file_bytes_cache[file_url] = (time.time(), content, content_type)
        if len(_file_bytes_cache) > 40:
            for stale, _ in sorted(_file_bytes_cache.items(), key=lambda x: x[1][0])[:10]:
                _file_bytes_cache.pop(stale, None)
    return content, content_type


def resolve_document_bytes(
    *,
    file_url: Optional[str],
    name: str,
    file_type: Optional[str],
    project_name: Optional[str],
    document_id: int,
) -> tuple[bytes, str, str]:
    """Return (bytes, content_type, filename)."""
    filename = name or f"document-{document_id}"

    if file_url and is_blob_url(file_url):
        content, content_type = fetch_blob_bytes(file_url)
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext in (".xlsx", ".xls"):
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif ext == ".pdf":
            content_type = "application/pdf"
        return content, content_type, filename

    content, content_type = generate_document_bytes(name, file_type, project_name, document_id)
    if not filename.lower().endswith((".pdf", ".xlsx", ".docx", ".dwg")):
        ext = (file_type or "pdf").lower()
        if ext == "xlsx":
            filename = f"{os.path.splitext(filename)[0]}.xlsx"
        elif ext in ("docx", "doc"):
            filename = f"{os.path.splitext(filename)[0]}.pdf"
        elif ext == "pdf":
            filename = f"{os.path.splitext(filename)[0]}.pdf"
    return content, content_type, filename


def resolve_drawing_bytes(
    *,
    file_url: Optional[str],
    drawing_no: str,
    title: str,
    discipline: Optional[str],
    revision: Optional[str],
    project_name: Optional[str],
    status: Optional[str],
) -> tuple[bytes, str, str]:
    if file_url and is_blob_url(file_url):
        content, content_type = fetch_blob_bytes(file_url)
        return content, content_type, _drawing_filename(drawing_no, title, file_url)

    raise FileNotFoundError(
        f"Drawing {drawing_no} has no file in blob storage. Upload it via the Drawings page."
    )


def _drawing_filename(drawing_no: str, title: str, blob_name: str) -> str:
    if blob_name and "." in blob_name.split("/")[-1]:
        return blob_name.split("/")[-1]
    safe = title.replace("/", "-").replace("\\", "-")
    return f"{drawing_no}_{safe}.png"
