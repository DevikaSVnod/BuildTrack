"""Factory for the configured SearchPipeline instance."""
from __future__ import annotations

from functools import lru_cache

from global_search_core.pipeline import SearchPipeline
from global_search_core.registry import get_connector

from app.plugins import register_all_plugins


@lru_cache(maxsize=1)
def get_search_pipeline() -> SearchPipeline:
    register_all_plugins()

    def _generate_answer(q, r, analysis=None):
        from app.search.answer import generate_answer

        return generate_answer(q, r, analysis=analysis)

    return SearchPipeline(
        connector=get_connector(),
        analyze_query=lambda query, top_k: __import__(
            "app.search.query_intel", fromlist=["analyze_query"]
        ).analyze_query(query, default_top_k=top_k),
        filter_for_query=lambda q, r, a: __import__(
            "app.search.result_filter", fromlist=["filter_results_for_query"]
        ).filter_results_for_query(q, r, a),
        filter_for_display=lambda q, ans, r, a: __import__(
            "app.search.result_filter", fromlist=["filter_results_for_display"]
        ).filter_results_for_display(q, ans, r, a),
        generate_answer=_generate_answer,
        get_cached_results=lambda q, ft, k, a, source_ids=None: __import__(
            "app.search.retrieval", fromlist=["get_cached_results"]
        ).get_cached_results(q, ft, k, a, source_ids),
    )
