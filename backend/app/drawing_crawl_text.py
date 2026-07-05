"""Build searchable text extracted from engineering drawing sheets (for RAG crawl)."""
from __future__ import annotations

from typing import Optional


def build_crawl_text(
    *,
    drawing_no: str,
    title: str,
    discipline: Optional[str] = None,
    revision: Optional[str] = None,
    project_name: Optional[str] = None,
    status: Optional[str] = None,
    sheet_notes: Optional[str] = None,
) -> str:
    """Plain-text representation of a drawing sheet for blob/RAG indexing."""
    notes = (sheet_notes or "").strip()

    lines = [
        "ENGINEERING DRAWING SHEET — EXTRACTED TEXT",
        f"Drawing No: {drawing_no}",
        f"Title: {title}",
        f"Discipline: {discipline or 'General'}",
        f"Revision: {revision or 'Rev A'}",
        f"Project: {project_name or 'Unassigned'}",
        f"Status: {status or 'Under Review'}",
        "",
        "SHEET CONTENT:",
        notes,
    ]
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def sidecar_filename(drawing_no: str) -> str:
    safe = drawing_no.replace("/", "-").replace("\\", "-")
    return f"{safe}_sheet_content.txt"
