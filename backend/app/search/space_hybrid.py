"""Hybrid Space retrieval: schema-SQL + existing data index + tool stubs."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings
from app.routing.source_router import route_query
from app.routing.tool_catalog import tool_stub_hits
from app.sql_agent.pipeline import (
    looks_free_text_content_query,
    looks_structured_db_query,
    run_schema_sql_retrieval,
)

logger = logging.getLogger(__name__)


def retrieve_space_hybrid(
    *,
    query: str,
    filter_type: Optional[str],
    top_k: int,
    analysis: Any,
    data_index_hits: list[dict[str, Any]],
    source_id: str = "space",
) -> list[dict[str, Any]]:
    """
    Merge schema-SQL hits with optional Azure data-index hits based on source router.
    `data_index_hits` may be empty for schema-only Space DBs (e.g. Project).
    """
    decision = route_query(query)
    logger.info(
        "Source router [%s]: %s (db=%.2f tool=%.2f) reasons=%s",
        source_id,
        decision.source,
        decision.db_score,
        decision.tool_score,
        decision.reasons[:6],
    )

    hits: list[dict[str, Any]] = []

    # Tool stubs only on primary Space Action for now
    if source_id == "space" and decision.source in ("TOOL", "BOTH"):
        hits.extend(tool_stub_hits(query))

    if decision.source in ("DB", "BOTH"):
        use_sql = settings.SCHEMA_SQL_ENABLED and (
            looks_structured_db_query(query) or not looks_free_text_content_query(query)
        )
        sql_hits: list[dict[str, Any]] = []
        if use_sql:
            result = run_schema_sql_retrieval(query, top_k=top_k, source_id=source_id)
            sql_hits = list(result.get("hits") or [])
            meta = result.get("meta") or {}
            if meta.get("error"):
                logger.info("Schema SQL path [%s]: %s", source_id, meta.get("error"))
            elif meta.get("sql"):
                logger.info(
                    "Schema SQL ok [%s] tables=%s sql=%s",
                    source_id,
                    meta.get("tables_used") or meta.get("tables"),
                    str(meta.get("sql"))[:160],
                )

        keep_data = bool(data_index_hits) and (
            looks_free_text_content_query(query)
            or not sql_hits
            or decision.source == "BOTH"
        )
        if keep_data:
            for h in data_index_hits:
                meta = dict(h.get("metadata") or {})
                meta.setdefault("retrieval", "data_index")
                h = dict(h)
                h["metadata"] = meta
                hits.append(h)

        if sql_hits:
            if looks_structured_db_query(query) and not looks_free_text_content_query(
                query
            ):
                hits = sql_hits + hits
            else:
                hits = hits + sql_hits

    return _dedupe(hits)[: max(top_k * 2, top_k)]


def _dedupe(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for h in hits:
        key = f"{h.get('content_type')}|{str(h.get('title') or '').strip().lower()}|{h.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    out.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return out
