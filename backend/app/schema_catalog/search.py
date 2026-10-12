"""Retrieve relevant schema tables for a user query from Azure schema index."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.core.config import settings
from app.schema_catalog.indexer import schema_index_name
from app.schema_catalog.models import DatabaseSnapshot, TableInfo
from app.schema_catalog.snapshot import load_current_snapshot
from app.search.indexer import get_search_client

logger = logging.getLogger(__name__)


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def search_relevant_tables(
    query: str,
    *,
    top_k: Optional[int] = None,
    source_id: str = "space",
) -> list[TableInfo]:
    """
    Return TableInfo objects from the current snapshot, ordered by schema-search relevance.
    Falls back to local hint matching if Azure schema index is empty/unavailable.
    """
    k = top_k or settings.SCHEMA_SQL_TOP_TABLES or 6
    snap = load_current_snapshot(source_id)
    if snap is None or not snap.tables:
        return []

    by_name = {t.name.lower(): t for t in snap.tables}
    ranked_names: list[str] = []

    client = get_search_client(schema_index_name())
    if client and settings.AZURE_SEARCH_ENDPOINT:
        try:
            from azure.search.documents.models import VectorizedQuery
            from app.search.embeddings import embed_text

            kwargs: dict[str, Any] = {
                "search_text": query,
                "top": max(k * 2, k),
                "query_type": "simple",
                "select": [
                    "id",
                    "title",
                    "content",
                    "content_type",
                    "metadata",
                    "source_database",
                ],
                # Narrow to this Space DB when the field exists on the index
                "filter": f"source_database eq '{source_id}'",
            }
            vector = embed_text(query)
            if vector:
                kwargs["vector_queries"] = [
                    VectorizedQuery(
                        vector=vector,
                        k_nearest_neighbors=k,
                        fields="content_vector",
                    )
                ]
            try:
                results = client.search(**kwargs)
            except Exception as filter_exc:
                # Older index may lack source_database — retry unfiltered
                logger.info(
                    "Schema search filter fallback (%s): %s", source_id, filter_exc
                )
                kwargs.pop("filter", None)
                results = client.search(**kwargs)
            for r in results:
                meta = _parse_meta(r.get("metadata"))
                doc_src = str(
                    r.get("source_database") or meta.get("database_id") or ""
                ).strip()
                if doc_src and doc_src != source_id:
                    continue
                tname = str(meta.get("table_name") or "").lower()
                if tname and tname in by_name and tname not in ranked_names:
                    ranked_names.append(tname)
        except Exception as exc:
            logger.warning("Schema Azure search failed, using local hints: %s", exc)

    if not ranked_names:
        ranked_names = _local_rank_tables(query, snap, k)

    out: list[TableInfo] = []
    for name in ranked_names[:k]:
        t = by_name.get(name)
        if t:
            out.append(t)
    return out


def _local_rank_tables(query: str, snap: DatabaseSnapshot, k: int) -> list[str]:
    q = query.lower()
    scored: list[tuple[float, str]] = []
    for t in snap.tables:
        score = 0.0
        blob = " ".join(
            [
                t.name.lower(),
                t.description.lower(),
                " ".join(h.lower() for h in t.search_hints),
                " ".join(c.name.lower() for c in t.columns),
            ]
        )
        for token in q.replace("/", " ").split():
            if len(token) < 3:
                continue
            if token in blob:
                score += 2.0
            if token in t.name.lower():
                score += 3.0
            for hint in t.search_hints:
                if token in hint.lower():
                    score += 2.5
        if score > 0:
            scored.append((score, t.name.lower()))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [n for _, n in scored[:k]]


def format_schema_for_prompt(tables: list[TableInfo], *, database_name: str) -> str:
    blocks: list[str] = []
    for t in tables:
        cols = ", ".join(
            f"{c.name}:{c.data_type}" + (" PK" if c.is_primary_key else "")
            for c in t.columns
        )
        fks = "; ".join(
            f"{fk.get('from_column')}->{fk.get('to_table')}.{fk.get('to_column')}"
            for fk in (t.foreign_keys or [])
        )
        blocks.append(
            f"TABLE {t.schema_name}.{t.name}  (database={database_name}; "
            f"use SQL schema '{t.schema_name}' only — not the database name)\n"
            f"Description: {t.description}\n"
            f"Columns: {cols}\n"
            f"FKs: {fks or '(none)'}"
        )
    return "\n\n".join(blocks)
