"""Upload document text sidecars for Azure blob / RAG indexing."""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Optional

from app.core.config import settings
from app.storage.document_blob import _sanitize_pdf_text

logger = logging.getLogger(__name__)

def build_document_crawl_text(document) -> str:
    body = (getattr(document, "body_text", None) or "").strip()
    lines = [
        "BUILDTRACK DOCUMENT — EXTRACTED TEXT",
        f"Document Id: {document.id}",
        f"Name: {document.name}",
        f"File Type: {document.file_type or 'UNKNOWN'}",
        f"Project Id: {document.project_id or ''}",
        "",
        "DOCUMENT CONTENT:",
        body or "(no extractable text)",
        "",
    ]
    return "\n".join(lines)


def sidecar_blob_name(document) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (document.name or f"doc-{document.id}"))
    return f"{uuid.uuid4()}_doc{document.id}_{base}_content.txt"


def upload_document_crawl_sidecar(document) -> Optional[str]:
    """Upload searchable text sidecar so the blob/RAG indexer can crawl document content."""
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        return None
    if not document.id:
        return None

    text = build_document_crawl_text(document)
    blob_name = sidecar_blob_name(document)

    from azure.storage.blob import BlobServiceClient, ContentSettings

    blob_service = BlobServiceClient.from_connection_string(
        settings.AZURE_STORAGE_CONNECTION_STRING
    )
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER)
    blob_client = container_client.get_blob_client(blob_name)
    metadata = {
        "original_filename": _sanitize_pdf_text(
            f"{os.path.splitext(document.name or 'document')[0]}_content.txt"
        ),
        "document_id": str(document.id),
        "content_type": "TXT",
        "size_bytes": str(len(text.encode("utf-8"))),
        "sidecar": "document_body",
    }
    if document.project_id is not None:
        metadata["project_id"] = str(document.project_id)

    blob_client.upload_blob(
        text.encode("utf-8"),
        overwrite=True,
        metadata=metadata,
        content_settings=ContentSettings(content_type="text/plain"),
    )
    return blob_client.url
