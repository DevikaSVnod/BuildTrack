"""
Operational page data — read from Azure AI Search only (SQL indexer output).

Writes still go to Azure SQL; the indexer syncs reads into the search index.
"""
import os
import uuid
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import get_db, ensure_drawing_file_columns
from app.models.user import User
from app.models.project import Project
from app.models.operational import EngineeringDrawing
from app.api.deps import get_current_user
from app.search import content_service
from app.search.sql_indexer import trigger_sql_indexer_async
from app.search.blob_indexer import trigger_blob_indexer_async
from app.search.index_purge import purge_after_sql_delete
from app.storage.document_blob import delete_document_blob, is_blob_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operational", tags=["operational"])


def _index_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/handover")
def list_handover(current_user: User = Depends(get_current_user)):
    try:
        return content_service.handover()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/drawings")
def list_drawings(current_user: User = Depends(get_current_user)):
    """List drawings from Azure AI Search (cached) — ids match /files/drawings/{id}."""
    try:
        return content_service.drawings()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


async def _upload_drawing_bytes(
    content: bytes, filename: str, original_filename: str
) -> tuple[str, int]:
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        return f"/uploads/{filename}", len(content)
    try:
        from azure.storage.blob import BlobServiceClient, ContentSettings

        size = len(content)
        blob_service = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER)
        blob_client = container_client.get_blob_client(filename)
        ext = os.path.splitext(filename)[1].lower()
        content_type = {
            ".pdf": "application/pdf",
            ".dwg": "application/vnd.dwg",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(ext, "application/octet-stream")
        await asyncio.to_thread(
            blob_client.upload_blob,
            content,
            overwrite=True,
            metadata={"original_filename": original_filename or filename},
            content_settings=ContentSettings(content_type=content_type),
        )
        return blob_client.url, size
    except Exception as exc:
        logger.warning("Drawing blob upload failed: %s", exc)
        return f"/uploads/{filename}", len(content)


@router.post("/drawings/upload", status_code=status.HTTP_201_CREATED)
async def upload_drawing(
    file: UploadFile = File(...),
    preview_file: Optional[UploadFile] = File(None),
    drawing_no: str = Form(...),
    title: str = Form(...),
    discipline: Optional[str] = Form(None),
    revision: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    status_value: Optional[str] = Form(None, alias="status"),
    sheet_notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_drawing_file_columns()
    drawing_no = drawing_no.strip()
    if not drawing_no:
        raise HTTPException(status_code=400, detail="Drawing number is required")

    existing = (
        db.query(EngineeringDrawing)
        .filter(EngineeringDrawing.drawing_no == drawing_no)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Drawing number {drawing_no} already exists",
        )

    ext = os.path.splitext(file.filename or "")[1].upper().lstrip(".") or "PDF"
    unique_name = f"{uuid.uuid4()}_{drawing_no}_{file.filename}"
    file_content = await file.read()
    file_url, file_size = await _upload_drawing_bytes(
        file_content, unique_name, file.filename or unique_name
    )

    project_name: Optional[str] = None
    if project_id is not None:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project_name = project.name

    preview_url: Optional[str] = None
    if preview_file and preview_file.filename:
        preview_bytes = await preview_file.read()
        preview_name = f"{uuid.uuid4()}_{drawing_no}_preview_{preview_file.filename}"
        preview_url, _ = await _upload_drawing_bytes(
            preview_bytes, preview_name, preview_file.filename
        )

    drawing = EngineeringDrawing(
        drawing_no=drawing_no,
        title=title,
        discipline=discipline,
        revision=revision or "Rev A",
        project_id=project_id,
        project_name=project_name,
        status=status_value or "Under Review",
        uploaded_by=current_user.full_name,
        file_url=file_url,
        preview_url=preview_url,
        file_type=ext,
        file_size=file_size,
    )
    db.add(drawing)
    db.commit()
    db.refresh(drawing)

    from app.storage.drawing_index import index_drawing_search_text

    notes = await asyncio.to_thread(
        index_drawing_search_text,
        drawing,
        user_notes=sheet_notes,
        db=db,
    )

    if settings.AZURE_STORAGE_CONNECTION_STRING and "blob.core.windows.net" in file_url:
        try:
            from azure.storage.blob import BlobServiceClient

            blob_service = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
            container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER)
            blob_client = container_client.get_blob_client(unique_name)
            await asyncio.to_thread(
                blob_client.set_blob_metadata,
                {
                    "drawing_id": str(drawing.id),
                    "drawing_no": drawing_no,
                    "original_filename": file.filename or unique_name,
                },
            )
        except Exception as exc:
            logger.debug("Drawing blob metadata update failed: %s", exc)

    trigger_sql_indexer_async()
    trigger_blob_indexer_async()
    return {
        "id": drawing.id,
        "drawingNo": drawing.drawing_no,
        "title": drawing.title,
        "discipline": drawing.discipline,
        "rev": drawing.revision,
        "project": drawing.project_name,
        "status": drawing.status,
        "uploadedBy": drawing.uploaded_by,
        "file_url": drawing.file_url,
        "file_type": drawing.file_type,
        "file_size": int(drawing.file_size or 0),
    }


def _delete_drawing_blobs(drawing: EngineeringDrawing) -> None:
    for url in (drawing.file_url, drawing.preview_url):
        if url and is_blob_url(url):
            try:
                delete_document_blob(url)
            except Exception as exc:
                logger.warning("Blob delete failed for drawing %s: %s", drawing.id, exc)


@router.delete("/drawings/{drawing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_drawing(
    drawing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_drawing_file_columns()
    drawing = db.query(EngineeringDrawing).filter(EngineeringDrawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    _delete_drawing_blobs(drawing)
    db.delete(drawing)
    db.commit()
    purge_after_sql_delete("drawing", drawing_id)
    trigger_sql_indexer_async()
    trigger_blob_indexer_async()


@router.get("/safety/incidents")
def list_safety_incidents(current_user: User = Depends(get_current_user)):
    try:
        return content_service.safety_incidents()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/safety/metrics")
def safety_metrics(current_user: User = Depends(get_current_user)):
    try:
        data = content_service.safety_metrics()
        if not data:
            raise HTTPException(status_code=404, detail="Safety KPI not found in search index")
        return data
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/attendance")
def list_attendance(current_user: User = Depends(get_current_user)):
    try:
        return content_service.attendance()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/timeline")
def list_timeline(current_user: User = Depends(get_current_user)):
    try:
        return content_service.timeline()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/reports/budget")
def budget_reports(current_user: User = Depends(get_current_user)):
    try:
        return content_service.budget_reports()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/reports/productivity")
def productivity_report(current_user: User = Depends(get_current_user)):
    try:
        data = content_service.productivity()
        if not data:
            raise HTTPException(status_code=404, detail="Productivity report not found in search index")
        return data
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/dashboard/milestones")
def dashboard_milestones(current_user: User = Depends(get_current_user)):
    try:
        return content_service.milestones()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/dashboard/site-activity")
def dashboard_site_activity(current_user: User = Depends(get_current_user)):
    try:
        data = content_service.site_activity()
        if not data:
            raise HTTPException(status_code=404, detail="Site activity KPI not found in search index")
        return data
    except RuntimeError as exc:
        raise _index_error(exc) from exc
