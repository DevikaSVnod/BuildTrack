import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User
from global_search_core.models import SearchRequest, SearchResponse
from app.search.pipeline_factory import get_search_pipeline
from app.api.deps import get_current_user

router = APIRouter(prefix="/search", tags=["search"])


def _context(db: Session) -> dict:
    return {"db": db}


# ── Fast search endpoint: returns results only, no AI ─────────────────────────
@router.post("/results", response_model=SearchResponse)
def fast_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns search results instantly — no AI answer generated."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    pipeline = get_search_pipeline()
    try:
        return pipeline.search_results(request, _context(db))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── AI answer endpoint: called after results are displayed ────────────────────
@router.post("/answer", response_model=SearchResponse)
def ai_answer(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generates AI answer using cached search results when available."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    pipeline = get_search_pipeline()
    try:
        return pipeline.search_with_answer(request, _context(db), use_cache=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Legacy combined endpoint (kept for compatibility) ─────────────────────────
@router.post("/", response_model=SearchResponse)
def global_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    pipeline = get_search_pipeline()
    try:
        return pipeline.search_combined(request, _context(db))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Clear search cache ────────────────────────────────────────────────────────
@router.post("/cache/clear", status_code=200)
def clear_cache(current_user: User = Depends(get_current_user)):
    from app.search.retrieval import _search_cache
    from app.search.answer import _answer_cache
    from app.search.cross_db_links import clear_cross_db_cache
    _search_cache.clear()
    _answer_cache.clear()
    clear_cross_db_cache()
    return {"message": "Search and answer caches cleared"}


# ── Plugin registry introspection (for integrators / debugging) ───────────────
@router.get("/plugins", status_code=200)
def list_plugins(current_user: User = Depends(get_current_user)):
    from global_search_core.registry import list_connectors, list_extractors
    from app.plugins import register_all_plugins

    register_all_plugins()
    return {
        "connectors": list_connectors(),
        "extractors": list_extractors(),
    }


@router.get("/sources", status_code=200)
def list_search_sources(current_user: User = Depends(get_current_user)):
    """List configured databases that Global Search can query."""
    from app.core.data_sources import ping_source, sources_public_info

    sources = sources_public_info()
    for src in sources:
        if src.get("enabled"):
            src["reachable"] = ping_source(src["id"])
        else:
            src["reachable"] = False
    return {"sources": sources, "count": len(sources)}


@router.post("/assets-index", status_code=200)
def sync_assets_index(current_user: User = Depends(get_current_user)):
    """Push Site Assets DB into its Azure AI Search index (multi-DB hybrid search)."""
    from app.search.assets_indexer import assets_index_doc_count, sync_assets_to_azure_search

    try:
        stats = sync_assets_to_azure_search(embed=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        **stats,
        "index_doc_count": stats.get("index_doc_count") or assets_index_doc_count(),
    }


@router.get("/assets-index/status", status_code=200)
def assets_index_status(current_user: User = Depends(get_current_user)):
    from app.core.config import settings
    from app.search.assets_indexer import assets_index_doc_count, assets_index_name

    return {
        "index": assets_index_name(),
        "configured": bool(settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_KEY),
        "doc_count": assets_index_doc_count(),
    }


# ── SQL Indexer (only supported path into Azure AI Search) ────────────────────
@router.post("/index", status_code=200)
def trigger_sql_indexer(current_user: User = Depends(get_current_user)):
    """Trigger Azure SQL Indexer run (same as automatic 15-min schedule)."""
    from app.search.sql_indexer import trigger_sql_indexer_run, get_sql_indexer_status

    try:
        trigger_sql_indexer_run()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "message": "Azure SQL Indexer run triggered — search will update from SQL shortly",
        **get_sql_indexer_status(),
    }


@router.get("/index/status", status_code=200)
def sql_indexer_status(current_user: User = Depends(get_current_user)):
    from app.search.sql_indexer import get_sql_indexer_status

    return get_sql_indexer_status()


@router.post("/blob-index", status_code=200)
def trigger_blob_indexer(current_user: User = Depends(get_current_user)):
    """Trigger Azure Blob/RAG indexer run (file content → search index)."""
    from app.search.blob_indexer import get_blob_indexer_status, trigger_blob_indexer_run

    try:
        triggered = trigger_blob_indexer_run()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "message": "Blob/RAG indexer run triggered — file content will update shortly",
        "triggered": triggered,
        **get_blob_indexer_status(),
    }


@router.get("/blob-index/status", status_code=200)
def blob_indexer_status(current_user: User = Depends(get_current_user)):
    from app.search.blob_indexer import get_blob_indexer_status

    return get_blob_indexer_status()
