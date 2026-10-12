from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from app.core.config import settings
from app.search.indexer import get_search_client, VECTOR_FIELD
from app.search.query_intel import (
    QueryAnalysis,
    analyze_query,
    rerank_score,
    is_workforce_aggregate_query,
    extract_project_qualifier,
    is_drawing_count_query,
    is_drawing_content_query,
    is_document_content_query,
    is_file_content_query,
)
from app.search.query_planner import QueryMode, plan_query
from app.search.structured_filters import execute_exhaustive_plan
from app.search.blob_retrieval import (
    enrich_drawing_hits_with_crawl_text,
    merge_sql_and_blob_hits,
    search_blob_content,
    should_search_blob_content,
)
import json
import time
import hashlib
import logging

logger = logging.getLogger(__name__)


def _get_query_vector(text: str) -> Optional[List[float]]:
    """Return embedding vector for the query, or None if not available."""
    try:
        from app.search.embeddings import embed_text
        return embed_text(text)
    except Exception as e:
        logger.debug(f"Query embedding skipped: {e}")
        return None

_search_cache: Dict[str, tuple] = {}
SEARCH_CACHE_TTL = 120

# Each source's deep search submits 3 tasks (embed + semantic + keyword), so the
# pool must fit every configured source or the multi-DB fan-out serializes here.
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="search")


def _search_cache_key(
    query: str,
    filter_type: Optional[str],
    top_k: int,
    analysis_key: str,
    search_index: Optional[str] = None,
) -> str:
    raw = f"{query.strip().lower()}|{filter_type}|{top_k}|{analysis_key}|{search_index or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def _merge_results(*lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    merged: List[Dict[str, Any]] = []
    for lst in lists:
        for item in lst:
            rid = item.get("id", "")
            if rid and rid not in seen:
                seen.add(rid)
                merged.append(item)
    return merged


def hybrid_search(
    query: str,
    filter_type: Optional[str] = None,
    top_k: int = 8,
    analysis: Optional[QueryAnalysis] = None,
    search_index: Optional[str] = None,
    security_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if analysis is None:
        analysis = analyze_query(query, default_top_k=top_k)

    plan = plan_query(query, analysis, filter_type=filter_type, top_k=top_k)
    effective_top = plan.max_results if plan.is_exhaustive() else (
        analysis.top_k if filter_type in (None, "all", "") else top_k
    )
    key = _search_cache_key(
        query,
        filter_type,
        effective_top,
        analysis.cache_suffix() + (f"|sec:{security_filter}" if security_filter else ""),
        search_index,
    )
    if key in _search_cache:
        ts, cached = _search_cache[key]
        if time.time() - ts < SEARCH_CACHE_TTL:
            try:
                from app.search.metrics import record_search
                record_search(0, top_k=len(cached), sources=1, cache_hit=True)
            except Exception:
                pass
            return cached

    client = get_search_client(search_index)
    if not client:
        return _fallback_results(query)

    t0 = time.time()
    try:
        # Exhaustive modes — filter / list-all (never top-K truncation)
        if plan.is_exhaustive() and plan.mode != QueryMode.WORKFORCE:
            exhaustive = execute_exhaustive_plan(plan, search_index=search_index)
            if exhaustive is None and plan.manager:
                # "Projects managed by X" is answered by project records alone.
                # An index without them (e.g. the assets DB) must return nothing —
                # a semantic fallback here answers a different question.
                exhaustive = []
            if exhaustive is not None:
                _search_cache[key] = (time.time(), exhaustive)
                return exhaustive

        filter_expr = None
        if filter_type and filter_type != "all":
            type_map = {
                "projects": "project",
                "tasks": "task",
                "documents": "document",
                "team": "team",
            }
            mapped = type_map.get(filter_type, filter_type)
            filter_expr = f"content_type eq '{mapped}'"
        elif analysis.content_types == ["team"] and not filter_type:
            # Workforce / role queries ("Who are the project managers?") must
            # not compete with document/project hits for result slots.
            filter_expr = "content_type eq 'team'"

        if security_filter:
            from app.search.security_trim import merge_odata
            filter_expr = merge_odata(filter_expr, security_filter)

        # Decide whether to embed this query.
        # Skip for very short / trivial queries — BM25 is sufficient and we save
        # the round-trip to Azure OpenAI (~1-3 s).
        _should_embed = analysis.is_question or len(query.split()) >= 5

        # Fire the embedding request in the background immediately so it can
        # overlap with the Azure AI Search round-trip.  We only harvest the
        # result once BM25 is done (non-blocking check with a short timeout).
        _f_embed = _executor.submit(_get_query_vector, query) if _should_embed else None

        def _run_search(search_text: str, use_semantic: bool, limit: int,
                        vector: Optional[List[float]] = None) -> list:
            kwargs: Dict[str, Any] = {
                "search_text": search_text,
                "top": limit,
                "select": ["id", "title", "content", "content_type", "url", "metadata"],
            }
            if filter_expr:
                kwargs["filter"] = filter_expr
            if use_semantic:
                kwargs["query_type"] = "semantic"
                kwargs["semantic_configuration_name"] = "default"

            # Attach vector query when a vector is available (hybrid search)
            if vector:
                try:
                    from azure.search.documents.models import VectorizedQuery
                    vq = VectorizedQuery(
                        vector=vector,
                        k_nearest_neighbors=limit,
                        fields=VECTOR_FIELD,
                    )
                    kwargs["vector_queries"] = [vq]
                except Exception as ve:
                    logger.debug(f"VectorizedQuery not attached: {ve}")

            rows = []
            for r in client.search(**kwargs):
                metadata = {}
                try:
                    metadata = json.loads(r.get("metadata", "{}") or "{}")
                except Exception:
                    pass
                rows.append({
                    "id": r.get("id", ""),
                    "title": r.get("title", ""),
                    "snippet": (r.get("content", "") or "")[:220],
                    "content_type": r.get("content_type", ""),
                    "url": r.get("url", ""),
                    "metadata": metadata,
                    "score": r.get("@search.score", 0),
                })
            return rows

        fetch_n = plan.fetch_limit if plan.mode == QueryMode.SEMANTIC else min(max(effective_top, 8), 20)

        def _resolve_vector(timeout: float = 4.0) -> Optional[List[float]]:
            """Return the embedding vector once it's ready, or None on timeout."""
            if _f_embed is None:
                return None
            try:
                return _f_embed.result(timeout=timeout)
            except Exception:
                return None

        # Workforce /team page: return all registered personnel (8 users)
        if is_workforce_aggregate_query(analysis.original):
            team_filter = filter_expr or "content_type eq 'team'"
            # For workforce queries, let the embedding finish (it's a short query)
            query_vector = _resolve_vector(timeout=4.0)

            def _team_search(search_text: str, limit: int) -> list:
                kwargs: Dict[str, Any] = {
                    "search_text": search_text,
                    "top": limit,
                    "select": ["id", "title", "content", "content_type", "url", "metadata"],
                    "filter": team_filter,
                }
                if query_vector:
                    try:
                        from azure.search.documents.models import VectorizedQuery
                        kwargs["vector_queries"] = [VectorizedQuery(
                            vector=query_vector,
                            k_nearest_neighbors=limit,
                            fields=VECTOR_FIELD,
                        )]
                    except Exception:
                        pass
                rows = []
                for r in client.search(**kwargs):
                    metadata = {}
                    try:
                        metadata = json.loads(r.get("metadata", "{}") or "{}")
                    except Exception:
                        pass
                    rows.append({
                        "id": r.get("id", ""),
                        "title": r.get("title", ""),
                        "snippet": (r.get("content", "") or "")[:220],
                        "content_type": r.get("content_type", ""),
                        "url": r.get("url", ""),
                        "metadata": metadata,
                        "score": r.get("@search.score", 0),
                    })
                return rows

            items = _team_search(
                "workforce personnel staff registered LMS team member", 20
            )
            if len(items) < 4:
                items = _merge_results(items, _team_search("*", 20))

            # One row per person (same as /team page)
            seen_users: set[int] = set()
            unique: List[Dict[str, Any]] = []
            for item in sorted(items, key=lambda x: x.get("score", 0), reverse=True):
                uid = item.get("metadata", {}).get("user_id")
                if uid is not None:
                    if uid in seen_users:
                        continue
                    seen_users.add(int(uid))
                unique.append(item)

            for item in unique:
                item["score"] = rerank_score(item, analysis)
            unique.sort(key=lambda x: x.get("score", 0), reverse=True)
            items = unique[:effective_top]
            _search_cache[key] = (time.time(), items)
            return items

        # Fast path: short keyword queries → BM25 + vector run in parallel.
        # Embedding fires in the background (_f_embed), BM25 also runs in parallel.
        # We wait for BM25 (fast, ~500ms) then check if embedding is done.
        is_drawing_count_fast = (
            is_drawing_count_query(query)
            and analysis.content_types == ["drawing"]
        )
        needs_deep_search = not is_drawing_count_fast and (
            analysis.is_question
            or bool(analysis.content_types)
            or bool(analysis.status_hints)
            or len(query.split()) > 6
        )

        if not needs_deep_search:
            # Run BM25 search on executor (parallel with background embedding)
            f_bm25 = _executor.submit(
                _run_search, analysis.search_text or query, False, fetch_n, None
            )
            bm25_items: List[Dict[str, Any]] = []
            try:
                bm25_items = f_bm25.result(timeout=8)
            except Exception as e:
                logger.warning(f"BM25 search failed: {e}")

            # Non-blocking check: did embedding finish while BM25 was running?
            query_vector = _resolve_vector(timeout=0.05)
            if query_vector and bm25_items:
                # Upgrade to hybrid: quick vector re-search and merge
                try:
                    hybrid_items = _run_search(
                        analysis.search_text or query, False, fetch_n, query_vector
                    )
                    items = _merge_results(hybrid_items, bm25_items)
                except Exception:
                    items = bm25_items
            else:
                items = bm25_items
        else:
            # Question / intent: 3 things in parallel —
            #   embedding, semantic search, keyword search
            keyword_text = analysis.search_text
            if analysis.content_types:
                keyword_text = f"{analysis.content_types[0]} {keyword_text}"

            semantic_items: List[Dict[str, Any]] = []
            keyword_items: List[Dict[str, Any]] = []

            # Both Azure calls run without vector first (immediate start)
            f_sem = _executor.submit(_run_search, analysis.original, True, fetch_n, None)
            f_kw = _executor.submit(_run_search, keyword_text, False, fetch_n, None)

            try:
                semantic_items = f_sem.result(timeout=10)
            except Exception as e:
                logger.warning(f"Semantic search failed: {e}")
            try:
                keyword_items = f_kw.result(timeout=10)
            except Exception as e:
                logger.warning(f"Keyword search failed: {e}")

            items = _merge_results(semantic_items, keyword_items)

            # If embedding is now ready, re-rank using vector similarity score
            query_vector = _resolve_vector(timeout=0.05)

        if not items:
            query_vector = _resolve_vector(timeout=2.0)
            items = _run_search(query, use_semantic=False, limit=fetch_n, vector=query_vector)

        if should_search_blob_content(plan, filter_type, query):
            blob_vector = _resolve_vector(timeout=1.5)
            blob_items = search_blob_content(
                query,
                search_text=analysis.search_text or query,
                top_k=min(max(effective_top, 8), 15),
                vector=blob_vector,
                use_semantic=needs_deep_search or analysis.is_question,
                multi_chunk=is_file_content_query(query),
            )
            if blob_items:
                items = merge_sql_and_blob_hits(items, blob_items)
            elif is_drawing_content_query(query):
                items = enrich_drawing_hits_with_crawl_text(items)

        for item in items:
            item["score"] = rerank_score(item, analysis)
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        items = items[:effective_top]

        _search_cache[key] = (time.time(), items)
        if len(_search_cache) > 300:
            oldest = sorted(_search_cache.items(), key=lambda x: x[1][0])[:80]
            for k, _ in oldest:
                del _search_cache[k]

        try:
            from app.search.metrics import record_search
            record_search(
                (time.time() - t0) * 1000,
                top_k=len(items),
                sources=1,
                cache_hit=False,
            )
        except Exception:
            pass
        return items

    except Exception as e:
        logger.error(f"Search error: {e}")
        return _fallback_results(query)


def get_cached_results(
    query: str,
    filter_type: Optional[str] = None,
    top_k: int = 8,
    analysis: Optional[QueryAnalysis] = None,
    source_ids: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return cached search results if /results was called moments before /answer."""
    if analysis is None:
        analysis = analyze_query(query, default_top_k=top_k)
    effective_top = analysis.top_k if filter_type in (None, "all", "") else top_k

    # Prefer multi-DB merged cache when multiple sources are configured.
    # Must use the same source narrowing as MultiDatabaseConnector.retrieve
    # (e.g. event/agenda → space only) so /answer does not miss the /results cache
    # and fall back to a broader multi-DB retrieve.
    try:
        from app.core.data_sources import select_sources_for_analysis

        sources = select_sources_for_analysis(analysis, source_ids)
        if len(sources) > 1:
            multi_key = _search_cache_key(
                query,
                filter_type,
                top_k,
                analysis.cache_suffix(),
                search_index="multi:" + ",".join(s.id for s in sources),
            )
            if multi_key in _search_cache:
                ts, cached = _search_cache[multi_key]
                if time.time() - ts < SEARCH_CACHE_TTL:
                    return cached
        elif len(sources) == 1:
            single_key = _search_cache_key(
                query,
                filter_type,
                effective_top,
                analysis.cache_suffix(),
                sources[0].search_index,
            )
            if single_key in _search_cache:
                ts, cached = _search_cache[single_key]
                if time.time() - ts < SEARCH_CACHE_TTL:
                    return cached
    except Exception:
        pass

    key = _search_cache_key(query, filter_type, effective_top, analysis.cache_suffix())
    if key in _search_cache:
        ts, cached = _search_cache[key]
        if time.time() - ts < SEARCH_CACHE_TTL:
            return cached
    return None


def _fallback_results(query: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "fallback-1",
            "title": "Azure Search Not Configured",
            "snippet": "Configure AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY in .env to enable real search.",
            "content_type": "project",
            "url": "/projects",
            "metadata": {},
            "score": 0,
        }
    ]
