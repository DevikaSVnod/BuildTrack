"""Upload drawing files and RAG sidecars to Azure Blob."""
from __future__ import annotations

import os
import uuid
from typing import Optional

from app.core.config import settings
from app.drawing_crawl_text import build_crawl_text, sidecar_filename
from app.storage.document_blob import _sanitize_pdf_text


def blob_name_for_drawing(drawing_id: int, drawing_no: str, asset_filename: str) -> str:
    safe_no = drawing_no.replace("/", "-").replace("\\", "-")
    return f"{uuid.uuid4()}_{safe_no}_{asset_filename}"


def upload_drawing_bytes_to_blob(
    content: bytes,
    blob_name: str,
    content_type: str,
    *,
    drawing_id: int,
    drawing_no: str,
    project_id: Optional[int],
    original_filename: str,
) -> tuple[str, int]:
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not configured")
    from azure.storage.blob import BlobServiceClient, ContentSettings

    size = len(content)
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER)
    blob_client = container_client.get_blob_client(blob_name)
    metadata = {
        "original_filename": _sanitize_pdf_text(original_filename),
        "drawing_id": str(drawing_id),
        "drawing_no": drawing_no,
        "content_type": os.path.splitext(original_filename)[1].lstrip(".").upper() or "PNG",
        "size_bytes": str(size),
    }
    if project_id is not None:
        metadata["project_id"] = str(project_id)
    blob_client.upload_blob(
        content,
        overwrite=True,
        metadata=metadata,
        content_settings=ContentSettings(content_type=content_type),
    )
    return blob_client.url, size


def upload_drawing_crawl_sidecar(drawing) -> Optional[str]:
    """Upload searchable text sidecar so the blob/RAG indexer can crawl drawing content."""
    project_name = drawing.project_name or (
        drawing.project.name if getattr(drawing, "project", None) else None
    )
    text = build_crawl_text(
        drawing_no=drawing.drawing_no,
        title=drawing.title,
        discipline=drawing.discipline,
        revision=drawing.revision,
        project_name=project_name,
        status=drawing.status,
        sheet_notes=drawing.sheet_notes,
        object_inventory=getattr(drawing, "object_inventory", None),
        sheet_intel=getattr(drawing, "sheet_intel", None),
    )
    sidecar = sidecar_filename(drawing.drawing_no)
    blob_name = blob_name_for_drawing(drawing.id, drawing.drawing_no, sidecar)
    url, _ = upload_drawing_bytes_to_blob(
        text.encode("utf-8"),
        blob_name,
        "text/plain",
        drawing_id=drawing.id,
        drawing_no=drawing.drawing_no,
        project_id=drawing.project_id,
        original_filename=sidecar,
    )
    return url
