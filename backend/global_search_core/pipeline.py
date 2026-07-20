"""Search pipeline — product orchestration layer (connector-agnostic)."""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from global_search_core.connector import SearchConnector, SearchContext
from global_search_core.models import SearchRequest, SearchResponse, SearchResultItem


AnalyzeQueryFn = Callable[[str, int], Any]
FilterForQueryFn = Callable[[str, list, Any], list]
FilterForDisplayFn = Callable[[str, str, list, Any], list]
GenerateAnswerFn = Callable[[str, list, Any], tuple[str, list[str]]]
GetCachedFn = Callable[[str, Optional[str], int, Any], Optional[list]]
CacheResultsFn = Callable[[str, Optional[str], int, Any, list], None]


class SearchPipeline:
    """
    Orchestrates search using a registered connector + host-provided intel/answer hooks.

    Core product code lives here; domain logic stays in connectors and app.search.* helpers.
    """

    def __init__(
        self,
        connector: SearchConnector,
        *,
        analyze_query: AnalyzeQueryFn,
        filter_for_query: FilterForQueryFn,
        filter_for_display: FilterForDisplayFn,
        generate_answer: GenerateAnswerFn,
        get_cached_results: Optional[GetCachedFn] = None,
        cache_results: Optional[CacheResultsFn] = None,
    ):
        self.connector = connector
        self.analyze_query = analyze_query
        self.filter_for_query = filter_for_query
        self.filter_for_display = filter_for_display
        self.generate_answer = generate_answer
        self.get_cached_results = get_cached_results
        self.cache_results = cache_results

    @staticmethod
    def _to_items(raw_results: list) -> list[SearchResultItem]:
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

    def _retrieve(
        self,
        *,
        context: SearchContext,
        query: str,
        filter_type: Optional[str],
        top_k: int,
        analysis: Any,
    ) -> list:
        return self.connector.retrieve(
            context=context,
            query=query,
            filter_type=filter_type,
            top_k=top_k,
            analysis=analysis,
        )

    def search_results(
        self,
        request: SearchRequest,
        context: SearchContext,
    ) -> SearchResponse:
        if not request.query.strip():
            raise ValueError("Query cannot be empty")

        analysis = self.analyze_query(request.query, request.top_k)
        start = time.time()
        raw = self._retrieve(
            context=context,
            query=request.query,
            filter_type=request.filter_type,
            top_k=request.top_k,
            analysis=analysis,
        )
        filtered = self.filter_for_query(request.query, raw, analysis)
        elapsed = int((time.time() - start) * 1000)

        return SearchResponse(
            ai_answer="",
            results=self._to_items(filtered),
            suggested_questions=[],
            search_time_ms=elapsed,
            total_results=len(filtered),
            is_question=getattr(analysis, "is_question", False),
        )

    def search_with_answer(
        self,
        request: SearchRequest,
        context: SearchContext,
        *,
        use_cache: bool = True,
    ) -> SearchResponse:
        if not request.query.strip():
            raise ValueError("Query cannot be empty")

        analysis = self.analyze_query(request.query, request.top_k)
        start = time.time()

        raw: list | None = None
        if use_cache and self.get_cached_results:
            raw = self.get_cached_results(
                request.query, request.filter_type, request.top_k, analysis
            )
            if raw is not None:
                raw = self.connector.enrich_cached(context=context, hits=raw)

        if raw is None:
            raw = self._retrieve(
                context=context,
                query=request.query,
                filter_type=request.filter_type,
                top_k=request.top_k,
                analysis=analysis,
            )

        answer_text, suggested = self.generate_answer(request.query, raw, analysis=analysis)
        filtered = self.filter_for_display(request.query, answer_text, raw, analysis)
        elapsed = int((time.time() - start) * 1000)

        return SearchResponse(
            ai_answer=answer_text,
            results=self._to_items(filtered),
            suggested_questions=suggested,
            search_time_ms=elapsed,
            total_results=len(filtered),
            is_question=getattr(analysis, "is_question", False),
        )

    def search_combined(
        self,
        request: SearchRequest,
        context: SearchContext,
    ) -> SearchResponse:
        """Single-call search + answer (legacy /combined endpoint)."""
        if not request.query.strip():
            raise ValueError("Query cannot be empty")

        analysis = self.analyze_query(request.query, request.top_k)
        start = time.time()
        raw = self._retrieve(
            context=context,
            query=request.query,
            filter_type=request.filter_type,
            top_k=request.top_k,
            analysis=analysis,
        )
        answer_text, suggested = self.generate_answer(request.query, raw, analysis=analysis)
        filtered = self.filter_for_display(request.query, answer_text, raw, analysis)
        elapsed = int((time.time() - start) * 1000)

        return SearchResponse(
            ai_answer=answer_text,
            results=self._to_items(filtered),
            suggested_questions=suggested,
            search_time_ms=elapsed,
            total_results=len(filtered),
            is_question=getattr(analysis, "is_question", False),
        )
