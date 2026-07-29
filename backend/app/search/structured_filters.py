"""
Exhaustive retrieval for filter / list-all query modes.

Uses Azure Search OData filters when index fields exist, with metadata scan fallback.
"""
from __future__ import annotations

from typing import Any, Optional

from app.search.index_reader import filter_indexed
from app.search.query_intel import QueryAnalysis
from app.search.query_planner import QueryMode, QueryPlan, is_list_all_query


def is_structured_filter_query(query: str) -> bool:
    from app.search.query_intel import (
        parse_manager_filter,
        parse_progress_filter,
        parse_status_filter,
    )

    return (
        parse_progress_filter(query) is not None
        or parse_status_filter(query) is not None
        or parse_manager_filter(query) is not None
        or is_list_all_query(query)
    )


def _meta_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _meta_status(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _status_matches(meta_status: Any, target: str) -> bool:
    ms = _meta_status(meta_status)
    ts = _meta_status(target)
    if not ms or not ts:
        return False
    return ms == ts or ts in ms or ms in ts


def _row_to_result(row: dict[str, Any], boost: float = 100.0) -> dict[str, Any]:
    content = row.get("content") or ""
    return {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "snippet": content[:220],
        "content_type": row.get("content_type", ""),
        "url": row.get("url", ""),
        "metadata": row.get("metadata") or {},
        "score": boost,
    }


def execute_exhaustive_plan(
    plan: QueryPlan,
    *,
    search_index: Optional[str] = None,
) -> Optional[list[dict[str, Any]]]:
    """
    Run FILTER or LIST_ALL mode — returns every matching record up to plan.max_results.

    `search_index` keeps each data source reading its own index; without it every
    source in a multi-DB fan-out returns the default index's rows under its label.
    """
    if not plan.is_exhaustive() or plan.mode == QueryMode.WORKFORCE:
        return None

    if plan.mode == QueryMode.LIST_ALL:
        rows = filter_indexed(
            content_types=plan.content_types,
            search_index=search_index,
            top=plan.max_results,
        )
    else:
        rows = filter_indexed(
            content_types=plan.content_types,
            progress=plan.progress,
            status=plan.status,
            project_manager=plan.manager,
            search_index=search_index,
            top=plan.max_results,
        )

    if not rows:
        return None

    type_order = {"project": 0, "timeline": 1, "task": 2, "document": 3}
    results = [_row_to_result(r) for r in rows]
    results.sort(
        key=lambda r: (
            type_order.get(r.get("content_type", ""), 9),
            (r.get("title") or "").lower(),
        )
    )
    return results[: plan.max_results]


def structured_filter_search(
    query: str,
    analysis: QueryAnalysis,
    *,
    filter_type: Optional[str] = None,
    plan: Optional[QueryPlan] = None,
) -> Optional[list[dict[str, Any]]]:
    """Legacy entry — prefer execute_exhaustive_plan via query_planner."""
    from app.search.query_planner import plan_query

    if plan is None:
        plan = plan_query(query, analysis, filter_type=filter_type)
    if not plan.is_exhaustive() or plan.mode == QueryMode.WORKFORCE:
        return None
    return execute_exhaustive_plan(plan)
