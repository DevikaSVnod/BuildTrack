import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.search.retrieval import hybrid_search, get_cached_results, _search_cache, _search_cache_key
from app.search.answer import generate_answer
from app.search.result_filter import filter_results_for_display, filter_results_for_query
from app.search.query_intel import analyze_query, is_workforce_aggregate_query, extract_project_qualifier
from app.search.workforce_db import workforce_results_from_db
from app.search.document_enrich import enrich_document_results
from app.api.deps import get_current_user

router = APIRouter(prefix="/search", tags=["search"])


def _resolve_search_results(
    query: str,
    db: Session,
    filter_type: Optional[str],
    top_k: int,
    analysis,
) -> list:
    """Workforce aggregate queries use DB (same as /team). Others use Azure."""
    if is_workforce_aggregate_query(query) and (not filter_type or filter_type == "all"):
        project_qual = extract_project_qualifier(query)
        results = workforce_results_from_db(db, project_qualifier=project_qual)
        key = _search_cache_key(
            query, filter_type, analysis.top_k, analysis.cache_suffix()
        )
        _search_cache[key] = (time.time(), results)
        return results
    raw = hybrid_search(
        query=query,
        filter_type=filter_type,
        top_k=top_k,
        analysis=analysis,
    )
    return enrich_document_results(db, raw)


def _to_result_items(raw_results):
    return [
        SearchResultItem(
            id=r["id"],
            title=r["title"],
            snippet=r["snippet"],
            content_type=r["content_type"],
            url=r["url"],
            metadata=r.get("metadata", {}),
            score=r.get("score", 0),
        )
        for r in raw_results
    ]


# ── Fast search endpoint: returns results only, no AI ─────────────────────────
@router.post("/results", response_model=SearchResponse)
def fast_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns Azure Search results instantly — no AI answer generated."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    analysis = analyze_query(request.query, default_top_k=request.top_k)
    start_time = time.time()
    raw_results = _resolve_search_results(
        request.query, db, request.filter_type, request.top_k, analysis
    )
    filtered = filter_results_for_query(request.query, raw_results, analysis)
    elapsed_ms = int((time.time() - start_time) * 1000)

    return SearchResponse(
        ai_answer="",
        results=_to_result_items(filtered),
        suggested_questions=[],
        search_time_ms=elapsed_ms,
        total_results=len(filtered),
        is_question=analysis.is_question,
    )


# ── AI answer endpoint: called after results are displayed ────────────────────
@router.post("/answer", response_model=SearchResponse)
def ai_answer(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generates AI answer using cached search results."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    analysis = analyze_query(request.query, default_top_k=request.top_k)
    start_time = time.time()
    # Reuse /results cache — avoids a second round of Azure calls
    raw_results = get_cached_results(
        request.query, request.filter_type, request.top_k, analysis
    )
    if raw_results is None:
        raw_results = _resolve_search_results(
            request.query, db, request.filter_type, request.top_k, analysis
        )
    else:
        raw_results = enrich_document_results(db, raw_results)
    answer_text, suggested_questions = generate_answer(
        request.query, raw_results, analysis=analysis
    )
    filtered = filter_results_for_display(
        request.query, answer_text, raw_results, analysis
    )
    elapsed_ms = int((time.time() - start_time) * 1000)

    return SearchResponse(
        ai_answer=answer_text,
        results=_to_result_items(filtered),
        suggested_questions=suggested_questions,
        search_time_ms=elapsed_ms,
        total_results=len(filtered),
        is_question=analysis.is_question,
    )


# ── Legacy combined endpoint (kept for compatibility) ─────────────────────────
@router.post("/", response_model=SearchResponse)
def global_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    analysis = analyze_query(request.query, default_top_k=request.top_k)
    start_time = time.time()
    raw_results = _resolve_search_results(
        request.query, db, request.filter_type, request.top_k, analysis
    )
    answer_text, suggested_questions = generate_answer(
        request.query, raw_results, analysis=analysis
    )
    filtered = filter_results_for_display(
        request.query, answer_text, raw_results, analysis
    )
    elapsed_ms = int((time.time() - start_time) * 1000)

    return SearchResponse(
        ai_answer=answer_text,
        results=_to_result_items(filtered),
        suggested_questions=suggested_questions,
        search_time_ms=elapsed_ms,
        total_results=len(filtered),
        is_question=analysis.is_question,
    )


# ── Clear search cache ────────────────────────────────────────────────────────
@router.post("/cache/clear", status_code=200)
def clear_cache(current_user: User = Depends(get_current_user)):
    from app.search.retrieval import _search_cache
    from app.search.answer import _answer_cache
    _search_cache.clear()
    _answer_cache.clear()
    return {"message": "Search and answer caches cleared"}


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
