import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from global_search_core.models import SearchRequest, SearchResponse
from app.search.pipeline_factory import get_search_pipeline
from app.api.deps import get_current_user, security
from app.search.space_auth import decode_space_token, hash_user_id, space_user_id
from app.search.space_module_search import (
    is_space_module_search_configured,
    space_module_search,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


def _context(db: Session, user: Optional[User] = None) -> dict:
    ctx = {"db": db}
    if user is not None:
        ctx["user"] = user
    return ctx


# ── Fast search endpoint: returns results only, no AI ─────────────────────────
@router.post("/results", response_model=SearchResponse)
def fast_search(
    body: SearchRequest,
    http_request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Returns search results instantly — no AI answer generated.

    SPACE JWTs fan out to Action + CMS module APIs.
    BuildTrack JWTs keep the existing Azure/SQL pipeline.
    """
    correlation_id = http_request.headers.get("x-correlation-id") or str(uuid4())
    response.headers["x-correlation-id"] = correlation_id

    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    token = credentials.credentials
    space_payload = decode_space_token(token)
    if space_payload is not None and is_space_module_search_configured():
        try:
            return space_module_search(
                body,
                token,
                correlation_id=correlation_id,
                user_hash=hash_user_id(space_user_id(space_payload)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    if decode_token(token) is None and is_space_module_search_configured():
        try:
            return space_module_search(body, token, correlation_id=correlation_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    current_user = get_current_user(credentials, db)
    pipeline = get_search_pipeline()
    try:
        return pipeline.search_results(body, _context(db, current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── AI answer endpoint: called after results are displayed ────────────────────
@router.post("/answer", response_model=SearchResponse)
def ai_answer(
    body: SearchRequest,
    http_request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Generates AI answer using Top-K results. SPACE JWTs use module APIs first."""
    correlation_id = http_request.headers.get("x-correlation-id") or str(uuid4())
    response.headers["x-correlation-id"] = correlation_id

    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    token = credentials.credentials
    space_payload = decode_space_token(token)
    if space_payload is not None and is_space_module_search_configured():
        from app.search.space_answer import generate_space_answer, looks_like_question

        try:
            result = space_module_search(
                body,
                token,
                correlation_id=correlation_id,
                user_hash=hash_user_id(space_user_id(space_payload)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        answer, questions = generate_space_answer(body.query, result.results)
        result.ai_answer = answer
        result.suggested_questions = questions
        result.is_question = looks_like_question(body.query)
        return result

    if decode_token(token) is None and is_space_module_search_configured():
        from app.search.space_answer import generate_space_answer, looks_like_question

        try:
            result = space_module_search(body, token, correlation_id=correlation_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        answer, questions = generate_space_answer(body.query, result.results)
        result.ai_answer = answer
        result.suggested_questions = questions
        result.is_question = looks_like_question(body.query)
        return result

    current_user = get_current_user(credentials, db)
    pipeline = get_search_pipeline()
    try:
        return pipeline.search_with_answer(
            body, _context(db, current_user), use_cache=True
        )
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
        return pipeline.search_combined(request, _context(db, current_user))
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


@router.post("/space-index", status_code=200)
def sync_space_index(current_user: User = Depends(get_current_user)):
    """Push Space Action Events/Agenda/Information into Azure AI Search."""
    from app.search.space_indexer import space_index_doc_count, sync_space_to_azure_search

    try:
        stats = sync_space_to_azure_search(embed=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        **stats,
        "index_doc_count": stats.get("index_doc_count") or space_index_doc_count(),
    }


@router.get("/space-index/status", status_code=200)
def space_index_status(current_user: User = Depends(get_current_user)):
    from app.core.config import settings
    from app.search import space_indexer as space_ix

    return {
        "index": space_ix.space_index_name(),
        "configured": bool(
            settings.SPACE_DATABASE_URL
            and settings.AZURE_SEARCH_ENDPOINT
            and settings.AZURE_SEARCH_KEY
        ),
        "space_database_configured": bool(settings.SPACE_DATABASE_URL),
        "schema": space_ix.SPACE_SCHEMA,
        "excluded_tables": sorted(space_ix.EXCLUDED_TABLES),
        "max_rows_per_table": settings.SPACE_INDEX_MAX_ROWS_PER_TABLE,
        "doc_count": space_ix.space_index_doc_count(),
        "last_discovery": getattr(space_ix.load_space_search_docs, "last_discovery", {}),
    }


@router.post("/schema-index", status_code=200)
def sync_schema_index(current_user: User = Depends(get_current_user)):
    """Refresh Space schema catalog and push table docs into Azure schema index."""
    from app.schema_catalog.indexer import (
        schema_index_doc_count,
        sync_schema_catalog_to_azure_search,
    )

    try:
        stats = sync_schema_catalog_to_azure_search(embed=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        **stats,
        "index_doc_count": stats.get("index_doc_count") or schema_index_doc_count(),
    }


@router.get("/schema-index/status", status_code=200)
def schema_index_status(current_user: User = Depends(get_current_user)):
    from app.core.config import settings
    from app.core.space_databases import (
        clear_space_db_cache,
        is_space_db_enabled,
        list_space_db_configs,
    )
    from app.schema_catalog.indexer import schema_index_doc_count, schema_index_name
    from app.schema_catalog.snapshot import load_current_snapshot

    clear_space_db_cache()
    sources = []
    for cfg in list_space_db_configs(enabled_only=False):
        snap = load_current_snapshot(cfg.source_id)
        sources.append(
            {
                "source_id": cfg.source_id,
                "label": cfg.label,
                "database_name": cfg.database_name,
                "schema_name": cfg.schema_name,
                "enabled": is_space_db_enabled(cfg),
                "schema_version": snap.version if snap else None,
                "tables": len(snap.tables) if snap else 0,
            }
        )
    return {
        "index": schema_index_name(),
        "configured": bool(
            settings.SPACE_DATABASE_URL
            and settings.AZURE_SEARCH_ENDPOINT
            and settings.AZURE_SEARCH_KEY
        ),
        "schema_sql_enabled": settings.SCHEMA_SQL_ENABLED,
        "sources": sources,
        "doc_count": schema_index_doc_count(),
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


# ── Production architecture: catalog, incremental sync, metrics ───────────────
@router.get("/catalog", status_code=200)
def get_schema_catalog(current_user: User = Depends(get_current_user)):
    """Schema catalog inventory — entities, tiers, and index field map."""
    from app.core.config import settings
    from app.search.catalog.inventory import inventory_snapshot

    return {
        "flags": {
            "SEARCH_HYDRATE_FROM_SQL": settings.SEARCH_HYDRATE_FROM_SQL,
            "SEARCH_CATALOG_ENABLED": settings.SEARCH_CATALOG_ENABLED,
            "SEARCH_INCREMENTAL_SYNC": settings.SEARCH_INCREMENTAL_SYNC,
            "SEARCH_SECURITY_TRIMMING": settings.SEARCH_SECURITY_TRIMMING,
            "SEARCH_CHUNK_INDEX_FOR_DOCS": settings.SEARCH_CHUNK_INDEX_FOR_DOCS,
        },
        **inventory_snapshot(),
    }


@router.post("/sync/incremental", status_code=200)
def run_incremental_sync(
    full: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Watermark-based incremental push of catalog entities into Azure AI Search."""
    from app.search.incremental_sync import sync_buildtrack_incremental

    try:
        return sync_buildtrack_incremental(db, embed=True, full=full)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/sync/status", status_code=200)
def sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.search.sync_state import list_sync_states

    return {"states": list_sync_states(db)}


@router.get("/metrics", status_code=200)
def search_metrics(current_user: User = Depends(get_current_user)):
    """In-process cost/latency metrics for search, hydrate, embeds, and LLM."""
    from app.search.metrics import snapshot

    return snapshot()
