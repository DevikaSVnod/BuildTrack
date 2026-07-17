"""Index a drawing: extract text from file, persist sheet_notes, upload RAG sidecar."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.search.drawing_text_extract import extract_drawing_sheet_notes
from app.search.object_inventory import (
    embed_inventory_in_notes,
    extract_object_inventory,
    inventory_to_search_text,
)
from app.search.drawing_sheet_intel import (
    embed_sheet_intel_in_notes,
    extract_drawing_sheet_intel,
    sheet_intel_to_search_text,
)
from app.storage.drawing_blob import upload_drawing_crawl_sidecar
from app.storage.drawing_content import (
    guess_file_type,
    resolve_drawing_file_bytes,
)
from app.storage.drawing_raster import ensure_drawing_raster_bytes

logger = logging.getLogger(__name__)


def index_drawing_search_text(
    drawing,
    *,
    user_notes: Optional[str] = None,
    db=None,
) -> str:
    """
    Extract searchable text from the drawing file, save to sheet_notes, upload sidecar.
    Also builds object inventory + sheet intel (scale/views/dims) for Q&A.
    Returns the combined sheet_notes string.
    """
    content, content_type, filename = resolve_drawing_file_bytes(drawing)
    file_type = drawing.file_type or guess_file_type(filename, content_type)

    preview_bytes: bytes | None = None
    preview_type = "image/png"
    try:
        preview_bytes, preview_type = ensure_drawing_raster_bytes(drawing, db=db)
    except Exception as exc:
        logger.warning("Could not rasterize %s for vision: %s", drawing.drawing_no, exc)

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

    # Structured object inventory from raster (PNG/JPG/DWG preview/PDF page)
    if preview_bytes:
        try:
            inventory = extract_object_inventory(preview_bytes, preview_type, use_tiling=True)
            if inventory and inventory.get("objects"):
                inv_text = inventory_to_search_text(inventory)
                if inv_text and inv_text not in notes:
                    notes = f"{notes.rstrip()}\n\n{inv_text}"
                notes = embed_inventory_in_notes(notes, inventory)
                try:
                    drawing.object_inventory = json.dumps(inventory, ensure_ascii=False)
                except Exception:
                    pass
                logger.info(
                    "Object inventory for %s: %s items",
                    drawing.drawing_no,
                    len(inventory.get("objects") or []),
                )
        except Exception as exc:
            logger.warning("Object inventory failed for %s: %s", drawing.drawing_no, exc)

        # Scale / views / dimensions / title block
        try:
            intel = extract_drawing_sheet_intel(preview_bytes, preview_type)
            if intel and intel.get("method") != "none":
                intel_text = sheet_intel_to_search_text(intel)
                if intel_text and intel_text not in notes:
                    notes = f"{notes.rstrip()}\n\n{intel_text}"
                notes = embed_sheet_intel_in_notes(notes, intel)
                try:
                    drawing.sheet_intel = json.dumps(intel, ensure_ascii=False)
                except Exception:
                    pass
                logger.info(
                    "Sheet intel for %s: scale=%s views=%s dims=%s",
                    drawing.drawing_no,
                    len(intel.get("scale") or []),
                    len(intel.get("views") or []),
                    len(intel.get("key_dimensions") or []),
                )
        except Exception as exc:
            logger.warning("Sheet intel failed for %s: %s", drawing.drawing_no, exc)

    drawing.sheet_notes = notes
    if db is not None:
        db.commit()

    try:
        upload_drawing_crawl_sidecar(drawing)
    except Exception as exc:
        logger.warning("Sidecar upload failed for %s: %s", drawing.drawing_no, exc)

    return notes
