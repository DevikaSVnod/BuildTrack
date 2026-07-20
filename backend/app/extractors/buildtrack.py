"""BuildTrack content extractors (drawing intelligence + document body text)."""
from __future__ import annotations

import json
from typing import Any

from global_search_core.extractor import ContentExtractor, ExtractionInput, ExtractionResult


class DrawingIntelligenceExtractor(ContentExtractor):
    """Upload-time drawing inventory + sheet intel (vision-backed)."""

    name = "drawing_intelligence"
    content_types = ("drawing",)

    def supports(self, content_type: str) -> bool:
        return content_type == "drawing"

    def extract(self, data: ExtractionInput) -> ExtractionResult:
        from app.search.drawing_sheet_intel import (
            extract_drawing_sheet_intel,
            sheet_intel_to_search_text,
        )
        from app.search.object_inventory import (
            embed_inventory_in_notes,
            embed_sheet_intel_in_notes,
            extract_object_inventory,
            inventory_to_search_text,
        )

        preview = data.metadata.get("preview_bytes") or data.file_bytes
        preview_type = data.metadata.get("preview_mime") or data.mime_type or "image/png"

        inventory = extract_object_inventory(preview, preview_type, use_tiling=True)
        intel = extract_drawing_sheet_intel(preview, preview_type)

        text_parts: list[str] = []
        if inventory and inventory.get("objects"):
            text_parts.append(inventory_to_search_text(inventory))
        if intel:
            text_parts.append(sheet_intel_to_search_text(intel))

        combined = "\n\n".join(p for p in text_parts if p)
        if inventory and inventory.get("objects"):
            combined = embed_inventory_in_notes(combined, inventory)
        if intel:
            combined = embed_sheet_intel_in_notes(combined, intel)

        return ExtractionResult(
            text=combined,
            structured={
                "object_inventory": inventory,
                "sheet_intel": intel,
            },
            sidecar_text=combined,
        )


class DocumentBodyTextExtractor(ContentExtractor):
    """Upload-time PDF/DOCX body text extraction."""

    name = "document_body_text"
    content_types = ("document",)

    def supports(self, content_type: str) -> bool:
        return content_type == "document"

    def extract(self, data: ExtractionInput) -> ExtractionResult:
        from app.search.document_text_extract import extract_document_body_text

        body = extract_document_body_text(
            content=data.file_bytes,
            file_type=data.metadata.get("file_type") or "",
            filename=data.metadata.get("filename") or "",
        )
        return ExtractionResult(
            text=body or "",
            structured={"body_text": body},
            sidecar_text=body or "",
        )
