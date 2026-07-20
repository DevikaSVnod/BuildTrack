"""BuildTrack reference connector — Azure Search + SQL enrich + workforce DB."""
from __future__ import annotations

from typing import Any, Optional

from global_search_core.connector import SearchConnector, SearchContext
from global_search_core.models import SearchHit


class BuildTrackConnector(SearchConnector):
    name = "buildtrack"

    def retrieve(
        self,
        *,
        context: SearchContext,
        query: str,
        filter_type: Optional[str],
        top_k: int,
        analysis: Any,
    ) -> list[SearchHit]:
        from app.search.query_intel import extract_project_qualifier, is_workforce_aggregate_query
        from app.search.retrieval import _search_cache, _search_cache_key, hybrid_search
        from app.search.workforce_db import workforce_results_from_db
        from app.search.document_enrich import enrich_document_results

        db = context.get("db")
        if db is None:
            raise RuntimeError("BuildTrackConnector requires context['db'] (SQLAlchemy session)")

        if is_workforce_aggregate_query(query) and (not filter_type or filter_type == "all"):
            project_qual = extract_project_qualifier(query)
            results = workforce_results_from_db(db, project_qualifier=project_qual)
            key = _search_cache_key(
                query, filter_type, analysis.top_k, analysis.cache_suffix()
            )
            _search_cache[key] = (__import__("time").time(), results)
            return results

        raw = hybrid_search(
            query=query,
            filter_type=filter_type,
            top_k=top_k,
            analysis=analysis,
        )
        return enrich_document_results(db, raw)

    def enrich_cached(
        self,
        *,
        context: SearchContext,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        from app.search.document_enrich import enrich_document_results

        db = context.get("db")
        if db is None:
            return hits
        return enrich_document_results(db, hits)
