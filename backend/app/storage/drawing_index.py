"""Index a drawing: extract text from file, persist sheet_notes, upload RAG sidecar."""
from __future__ import annotations

import logging
from typing import Optional

from app.search.drawing_text_extract import extract_drawing_sheet_notes
from app.storage.drawing_blob import upload_drawing_crawl_sidecar
from app.storage.drawing_content import (
    guess_file_type,
    resolve_drawing_file_bytes,
    resolve_drawing_image_bytes,
)
from app.storage.drawing_preview import ensure_dwg_preview_png

logger = logging.getLogger(__name__)


def index_drawing_search_text(
    drawing,
    *,
    user_notes: Optional[str] = None,
    db=None,
) -> str:
    """
    Extract searchable text from the drawing file, save to sheet_notes, upload sidecar.
    Returns the combined sheet_notes string.
    """
    content, content_type, filename = resolve_drawing_file_bytes(drawing)
    file_type = drawing.file_type or guess_file_type(filename, content_type)

    if file_type == "DWG":
        ensure_dwg_preview_png(drawing, content, db=db)

    preview = resolve_drawing_image_bytes(drawing)
    preview_bytes: bytes | None = None
    preview_type = "image/png"
    if preview:
        preview_bytes, preview_type = preview

    notes = extract_drawing_sheet_notes(
        content=content,
        file_type=file_type,
        drawing_no=drawing.drawing_no,
        title=drawing.title,
        discipline=drawing.discipline,
        user_notes=user_notes,
        existing_notes=drawing.sheet_notes,
        preview_content=preview_bytes,
        preview_content_type=preview_type,
    )
    drawing.sheet_notes = notes
    if db is not None:
        db.commit()

    try:
        upload_drawing_crawl_sidecar(drawing)
    except Exception as exc:
        logger.warning("Sidecar upload failed for %s: %s", drawing.drawing_no, exc)

    return notes
