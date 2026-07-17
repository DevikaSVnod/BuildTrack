"""Read files from Azure Blob (or generate placeholders for legacy /uploads paths)."""
from __future__ import annotations

import mimetypes
import os
import urllib.parse
from typing import Optional

from app.core.config import settings
from app.storage.document_blob import generate_document_bytes, is_blob_url


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


def fetch_blob_bytes(file_url: str) -> tuple[bytes, str]:
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("Azure Storage is not configured")
    from azure.storage.blob import BlobServiceClient

    container, blob_name = parse_blob_url(file_url)
    client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob = client.get_blob_client(container=container, blob=blob_name)
    props = blob.get_blob_properties()
    content_type = (props.content_settings.content_type if props.content_settings else None) or _guess_content_type(blob_name)
    # Some uploads may have incorrect content-type metadata; for vision calls we must
    # provide an image/* MIME when the blob name indicates an image.
    guessed = _guess_content_type(blob_name)
    if guessed and guessed.startswith("image/"):
        content_type = guessed
    return blob.download_blob().readall(), content_type


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
