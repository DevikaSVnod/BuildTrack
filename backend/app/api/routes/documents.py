from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import uuid
import os
import logging
import asyncio
from app.core.database import get_db
from app.search import content_service
from app.core.config import settings
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentCreate
from app.api.deps import get_current_user
from app.search.sql_indexer import trigger_sql_indexer_async
from app.search.blob_indexer import trigger_blob_indexer_async
from app.search.index_purge import purge_after_sql_delete
from app.storage.document_blob import delete_document_blob, is_blob_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


def enrich_document(doc: Document) -> dict:
    return {
        "id": doc.id,
        "name": doc.name,
        "file_type": doc.file_type,
        "file_url": doc.file_url,
        "project_id": doc.project_id,
        "uploaded_by": doc.uploaded_by,
        "file_size": doc.file_size,
        "created_at": doc.created_at,
        "uploader": doc.uploader,
        "project_name": doc.project.name if doc.project else None,
    }


async def upload_to_azure(file: UploadFile, filename: str) -> tuple[str, int]:
    """Upload file bytes to Azure Blob. Returns (url, size_in_bytes)."""
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        return f"/uploads/{filename}", 0
    try:
        from azure.storage.blob import BlobServiceClient, ContentSettings
        content = await file.read()
        size = len(content)
        blob_service = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER)
        blob_client = container_client.get_blob_client(filename)
        ext = os.path.splitext(filename)[1].lower()
        content_type = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".dwg": "application/octet-stream",
        }.get(ext, "application/octet-stream")
        await asyncio.to_thread(
            blob_client.upload_blob,
            content,
            overwrite=True,
            metadata={
                "original_filename": file.filename or filename,
                "content_type": ext.lstrip(".").upper(),
                "size_bytes": str(size),
            },
            content_settings=ContentSettings(content_type=content_type),
        )
        return blob_client.url, size
    except Exception as e:
        logger.warning(f"Blob upload failed, using local path: {e}")
        return f"/uploads/{filename}", file.size or 0


@router.get("/", response_model=List[DocumentResponse])
def list_documents(
    project_id: Optional[int] = None,
    file_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """List documents from Azure AI Search (cached) — ids match /files/documents/{id}."""
    try:
        return content_service.documents(project_id=project_id, file_type=file_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename)[1].upper().lstrip(".")
    unique_name = f"{uuid.uuid4()}_{file.filename}"
    file_url, file_size = await upload_to_azure(file, unique_name)
    doc = Document(
        name=file.filename,
        file_type=ext or "UNKNOWN",
        file_url=file_url,
        project_id=project_id,
        uploaded_by=current_user.id,
        file_size=file_size,
    )
    db.add(doc)
    db.commit()
    doc = (
        db.query(Document)
        .options(joinedload(Document.project), joinedload(Document.uploader))
        .filter(Document.id == doc.id)
        .first()
    )
    # Search index: SQL metadata indexer + blob RAG indexer (file content)
    trigger_sql_indexer_async()
    trigger_blob_indexer_async()
    return DocumentResponse(**enrich_document(doc))


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if is_blob_url(doc.file_url):
        try:
            delete_document_blob(doc.file_url)
        except Exception as exc:
            logger.warning("Blob delete failed for document %s: %s", doc_id, exc)
    db.delete(doc)
    db.commit()
    purge_after_sql_delete("document", doc_id)
    trigger_sql_indexer_async()
    trigger_blob_indexer_async()
