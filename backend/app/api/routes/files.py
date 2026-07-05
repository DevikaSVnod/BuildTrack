"""Authenticated view/download for documents and drawings."""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.document import Document
from app.models.operational import EngineeringDrawing
from app.models.user import User
from app.storage.blob_access import resolve_document_bytes, resolve_drawing_bytes

router = APIRouter(prefix="/files", tags=["files"])


def _safe_filename(name: str) -> str:
    return name.replace('"', "").replace("\n", "").replace("\r", "") or "file"


def _file_response(
    content: bytes,
    content_type: str,
    filename: str,
    *,
    download: bool,
) -> Response:
    disposition = "attachment" if download else "inline"
    safe = _safe_filename(filename)
    encoded = urllib.parse.quote(safe)
    headers = {
        "Content-Disposition": f'{disposition}; filename="{safe}"; filename*=UTF-8\'\'{encoded}',
        "Cache-Control": "private, max-age=300",
    }
    return Response(content=content, media_type=content_type, headers=headers)


@router.get("/documents/{doc_id}")
def get_document_file(
    doc_id: int,
    download: bool = Query(False, description="Force download instead of inline view"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = (
        db.query(Document)
        .options(joinedload(Document.project))
        .filter(Document.id == doc_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    project_name = doc.project.name if doc.project else None
    try:
        content, content_type, filename = resolve_document_bytes(
            file_url=doc.file_url,
            name=doc.name,
            file_type=doc.file_type,
            project_name=project_name,
            document_id=doc.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load file: {exc}") from exc

    return _file_response(content, content_type, filename, download=download)


def _load_drawing_response(drawing: EngineeringDrawing, *, download: bool) -> Response:
    project_name = drawing.project_name or (drawing.project.name if drawing.project else None)
    try:
        content, content_type, filename = resolve_drawing_bytes(
            file_url=drawing.file_url,
            drawing_no=drawing.drawing_no,
            title=drawing.title,
            discipline=drawing.discipline,
            revision=drawing.revision,
            project_name=project_name,
            status=drawing.status,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load drawing: {exc}") from exc

    return _file_response(content, content_type, filename, download=download)


@router.get("/drawings/by-no/{drawing_no}")
def get_drawing_file_by_no(
    drawing_no: str,
    download: bool = Query(False, description="Force download instead of inline view"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stable file access by drawing number (survives DB re-seed / id changes)."""
    drawing = (
        db.query(EngineeringDrawing)
        .options(joinedload(EngineeringDrawing.project))
        .filter(EngineeringDrawing.drawing_no == drawing_no)
        .first()
    )
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return _load_drawing_response(drawing, download=download)


@router.get("/drawings/{drawing_id}")
def get_drawing_file(
    drawing_id: int,
    download: bool = Query(False, description="Force download instead of inline view"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    drawing = (
        db.query(EngineeringDrawing)
        .options(joinedload(EngineeringDrawing.project))
        .filter(EngineeringDrawing.id == drawing_id)
        .first()
    )
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return _load_drawing_response(drawing, download=download)
