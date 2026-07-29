"""
Central query planner — permanent routing for all search requests.

Every query is classified ONCE into a retrieval mode:
  FILTER    → exact metadata match, return ALL matches (never top-K)
  LIST_ALL  → enumerate every record of a type
  WORKFORCE → full personnel list (deduped)
  SEMANTIC  → hybrid keyword + vector (best-effort ranking)

Add new behaviour here instead of patching retrieval.py per query.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from app.search.query_intel import (
    QueryAnalysis,
    parse_manager_filter,
    parse_progress_filter,
    parse_status_filter,
    target_content_types_for_filter,
    is_workforce_aggregate_query,
    _normalize,
)

# Max records returned for exhaustive modes (FILTER / LIST_ALL / WORKFORCE)
EXHAUSTIVE_CAP = 100

# Semantic search fetch size — high enough to avoid dropping relevant hits
SEMANTIC_FETCH_MIN = 20
SEMANTIC_FETCH_MAX = 40


class QueryMode(str, Enum):
    FILTER = "filter"
    LIST_ALL = "list_all"
    WORKFORCE = "workforce"
    SEMANTIC = "semantic"


@dataclass
class QueryPlan:
    mode: QueryMode
    content_types: List[str] = field(default_factory=list)
    progress: Optional[int] = None
    status: Optional[str] = None
    manager: Optional[str] = None
    max_results: int = EXHAUSTIVE_CAP
    fetch_limit: int = SEMANTIC_FETCH_MIN

    def is_exhaustive(self) -> bool:
        return self.mode in (QueryMode.FILTER, QueryMode.LIST_ALL, QueryMode.WORKFORCE)


_LIST_ALL_RE = re.compile(
    r"\b(?:all|every|list|show|display|get)\s+"
    r"(projects?|tasks?|documents?|drawings?|phases?|timeline|incidents?|"
    r"activities|members?|personnel|workforce)\b",
    re.IGNORECASE,
)

_HOW_MANY_RE = re.compile(
    r"\bhow many\s+(projects?|tasks?|documents?|incidents?|members?|personnel)\b",
    re.IGNORECASE,
)


def _content_types_from_filter_chip(filter_type: Optional[str]) -> Optional[List[str]]:
    if not filter_type or filter_type in ("all", ""):
        return None
    type_map = {
        "projects": "project",
        "tasks": "task",
        "documents": "document",
    }
    return [type_map.get(filter_type, filter_type)]


def _content_types_from_list_query(query: str, analysis: QueryAnalysis) -> List[str]:
    q = _normalize(query)
    mapping = {
        "project": "project",
        "projects": "project",
        "task": "task",
        "tasks": "task",
        "document": "document",
        "documents": "document",
        "drawing": "drawing",
        "drawings": "drawing",
        "phase": "timeline",
        "phases": "timeline",
        "timeline": "timeline",
        "incident": "safety",
        "incidents": "safety",
        "activit": "task",
        "activities": "task",
        "member": "team",
        "members": "team",
        "personnel": "team",
        "workforce": "team",
    }
    for token, ctype in mapping.items():
        if re.search(rf"\b{re.escape(token)}\b", q):
            return [ctype]
    if analysis.content_types:
        return list(dict.fromkeys(analysis.content_types))
    return ["project", "task", "document", "team"]


def is_list_all_query(query: str) -> bool:
    q = _normalize(query)
    if _LIST_ALL_RE.search(q):
        return True
    if _HOW_MANY_RE.search(q):
        return True
    return q in {
        "all projects", "list projects", "show projects",
        "all tasks", "list tasks", "all documents", "list documents",
    }


def plan_query(
    query: str,
    analysis: QueryAnalysis,
    *,
    filter_type: Optional[str] = None,
    top_k: int = 8,
) -> QueryPlan:
    """
    Decide how to retrieve results for this query.
    This is the single place to extend when new query patterns appear.
    """
    chip_types = _content_types_from_filter_chip(filter_type)

    # 1) Workforce aggregate — always exhaustive
    if is_workforce_aggregate_query(query) and chip_types is None:
        return QueryPlan(mode=QueryMode.WORKFORCE, content_types=["team"], max_results=20)

    progress = parse_progress_filter(query)
    status = parse_status_filter(query)
    manager = parse_manager_filter(query)

    # 2) Exact metadata filter — always exhaustive
    if progress is not None or status is not None or manager:
        if manager:
            types = chip_types or ["project"]
        else:
            types = chip_types or target_content_types_for_filter(query, analysis)
        return QueryPlan(
            mode=QueryMode.FILTER,
            content_types=types,
            progress=progress,
            status=status,
            manager=manager,
            max_results=EXHAUSTIVE_CAP,
        )

    # 3) List / count all of a type — exhaustive
    if is_list_all_query(query) and chip_types is None:
        types = _content_types_from_list_query(query, analysis)
        return QueryPlan(mode=QueryMode.LIST_ALL, content_types=types, max_results=EXHAUSTIVE_CAP)

    if chip_types and is_list_all_query(query):
        return QueryPlan(mode=QueryMode.LIST_ALL, content_types=chip_types, max_results=EXHAUSTIVE_CAP)

    # 4) Semantic hybrid — ranked, but fetch enough candidates before trimming
    fetch = min(max(analysis.top_k, top_k, SEMANTIC_FETCH_MIN) * 2, SEMANTIC_FETCH_MAX)
    if analysis.is_question:
        fetch = SEMANTIC_FETCH_MAX
    if analysis.content_types:
        fetch = max(fetch, 25)

    return QueryPlan(
        mode=QueryMode.SEMANTIC,
        content_types=analysis.content_types,
        max_results=analysis.top_k,
        fetch_limit=fetch,
    )
