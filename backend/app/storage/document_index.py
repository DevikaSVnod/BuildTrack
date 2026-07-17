"""Index a document: extract body text, persist body_text, upload RAG text sidecar."""
from __future__ import annotations

import logging
from typing import Optional

from app.search.document_text_extract import extract_document_body_text
from app.storage.blob_access import fetch_blob_bytes, is_blob_url

logger = logging.getLogger(__name__)


def _load_document_bytes(document) -> tuple[bytes, str]:
    url = document.file_url or ""
    if not url or not is_blob_url(url):
        raise FileNotFoundError(
            f"Document {document.id} has no blob file. Upload it via the Documents page."
        )
    content, content_type = fetch_blob_bytes(url)
    return content, content_type


def index_document_search_text(document, *, db=None) -> str:
    """
    Extract searchable text from the document file and save to body_text.
    Also uploads a plain-text sidecar for the blob/RAG indexer.
    Returns the extracted body_text.
    """
    try:
        content, _content_type = _load_document_bytes(document)
    except Exception as exc:
        logger.warning("Could not load document %s bytes: %s", document.id, exc)
        return (getattr(document, "body_text", None) or "") or ""

    text = extract_document_body_text(
        content=content,
        file_type=document.file_type or "",
        filename=document.name or "",
    )
    if text:
        document.body_text = text
        if db is not None:
            try:
                db.commit()
            except Exception as exc:
                logger.warning("Failed to save body_text for document %s: %s", document.id, exc)
                db.rollback()
        logger.info(
            "Document body_text for %s (%s): %s chars",
            document.id,
            document.name,
            len(text),
        )
    else:
        logger.warning(
            "No text extracted for document %s (%s, type=%s)",
            document.id,
            document.name,
            document.file_type,
        )

    try:
        from app.storage.document_crawl import upload_document_crawl_sidecar

        upload_document_crawl_sidecar(document)
    except Exception as exc:
        logger.warning("Document sidecar upload failed for %s: %s", document.id, exc)

    return text or ""
