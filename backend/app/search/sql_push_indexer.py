"""
Push primary-DB rows into Azure AI Search from the app.

Used when the managed Azure SQL indexer cannot reach the database
(local SQL Server / non-Azure hosts). Same document shape as
vw_global_search_documents → buildtrack-index.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import SessionLocal
from app.search.indexer import (
    build_document_doc,
    build_project_doc,
    build_task_doc,
    build_unique_workforce_docs,
    ensure_index_exists,
    index_documents,
)

logger = logging.getLogger(__name__)


def _enrich_filter_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """Map metadata JSON into top-level filterable index fields."""
    try:
        meta = json.loads(doc.get("metadata") or "{}")
    except Exception:
        meta = {}
    if "progress" in meta and meta["progress"] is not None:
        try:
            doc["progress_pct"] = int(meta["progress"])
        except (TypeError, ValueError):
            pass
    status = meta.get("status")
    if status:
        doc["record_status"] = str(status)
    return doc


def load_primary_search_docs(db: Optional[Session] = None) -> list[dict[str, Any]]:
    """Build search documents from the primary app SQL tables."""
    from app.models.document import Document
    from app.models.project import Project
    from app.models.task import Task
    from app.models.team import TeamMember

    owns_session = db is None
    session = db or SessionLocal()
    docs: list[dict[str, Any]] = []
    try:
        projects = (
            session.query(Project)
            .options(joinedload(Project.project_manager))
            .all()
        )
        for project in projects:
            docs.append(_enrich_filter_fields(build_project_doc(project)))

        tasks = (
            session.query(Task)
            .options(joinedload(Task.project), joinedload(Task.assignee))
            .all()
        )
        for task in tasks:
            docs.append(_enrich_filter_fields(build_task_doc(task)))

        documents = (
            session.query(Document)
            .options(joinedload(Document.project), joinedload(Document.uploader))
            .all()
        )
        for document in documents:
            doc = build_document_doc(document)
            # Production: keep full body in blob/RAG chunks, not the entity index.
            if not settings.SEARCH_CHUNK_INDEX_FOR_DOCS:
                body = (getattr(document, "body_text", None) or "").strip()
                if body:
                    doc["content"] = f"{doc['content']} {body}".strip()
            docs.append(_enrich_filter_fields(doc))

        members = (
            session.query(TeamMember)
            .options(joinedload(TeamMember.user), joinedload(TeamMember.project))
            .all()
        )
        docs.extend(build_unique_workforce_docs(members))
    finally:
        if owns_session:
            session.close()

    return docs


def push_docs_now(docs: list[dict[str, Any]], *, embed: bool = True) -> dict[str, Any]:
    """Upload specific docs immediately and clear the page-read cache."""
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        raise RuntimeError("Azure Search is not configured (AZURE_SEARCH_ENDPOINT / KEY)")
    if not docs:
        return {"index": settings.AZURE_SEARCH_INDEX, "uploaded_ok": 0, "uploaded_failed": 0}

    index = settings.AZURE_SEARCH_INDEX
    if not ensure_index_exists(index):
        raise RuntimeError(f"Failed to create/update Azure Search index {index}")

    prepared = [_enrich_filter_fields(dict(d)) for d in docs if d]
    result = index_documents(prepared, embed=embed, index_name=index)
    try:
        from app.search.index_reader import clear_index_cache

        clear_index_cache()
    except Exception:
        pass
    return {
        "index": index,
        "mode": "push",
        "documents_loaded": len(prepared),
        "uploaded_ok": result.get("ok", 0),
        "uploaded_failed": result.get("failed", 0),
        "message": f"Pushed {result.get('ok', 0)} doc(s) into '{index}'",
    }


def sync_primary_db_to_azure_search(*, embed: bool = True) -> dict[str, Any]:
    """Push primary-DB search docs into AZURE_SEARCH_INDEX (incremental when enabled)."""
    if settings.SEARCH_INCREMENTAL_SYNC and settings.SEARCH_CATALOG_ENABLED:
        session = SessionLocal()
        try:
            from app.search.incremental_sync import sync_buildtrack_incremental

            result = sync_buildtrack_incremental(session, embed=embed, full=False)
            # Still push workforce docs (not yet in catalog incremental path)
            docs = load_primary_search_docs()
            workforce = [d for d in docs if d.get("content_type") == "team"]
            if workforce:
                pushed = push_docs_now(workforce, embed=embed)
                result["workforce"] = pushed
            result["index"] = settings.AZURE_SEARCH_INDEX
            result["message"] = (
                f"Incremental sync changed {result.get('total_changed', 0)} rows "
                f"into '{settings.AZURE_SEARCH_INDEX}'"
            )
            return result
        finally:
            session.close()

    docs = load_primary_search_docs()
    if not docs:
        return {
            "index": settings.AZURE_SEARCH_INDEX,
            "mode": "push",
            "documents_loaded": 0,
            "uploaded_ok": 0,
            "uploaded_failed": 0,
            "message": "Primary DB has no indexable rows",
        }
    result = push_docs_now(docs, embed=embed)
    result["message"] = (
        f"Pushed {result.get('uploaded_ok', 0)} docs from local/primary SQL "
        f"into Azure AI Search index '{settings.AZURE_SEARCH_INDEX}'"
    )
    return result
