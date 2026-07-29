"""SQL text search against a data source's search_documents table."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _tokens(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]


def sql_search_documents(
    db: Session,
    query: str,
    *,
    filter_type: Optional[str] = None,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """
    Rank rows in search_documents by simple token overlap.
    Works for SQLite / Postgres / SQL Server when the table exists.
    """
    tokens = _tokens(query)
    type_map = {
        "vendors": "vendor",
        "equipment": "equipment",
        "materials": "material",
        "material": "material",
        "vendor": "vendor",
    }
    content_type = None
    if filter_type and filter_type not in ("all", ""):
        content_type = type_map.get(filter_type, filter_type)

    try:
        if content_type:
            rows = db.execute(
                text(
                    "SELECT id, title, content, content_type, url, metadata_json "
                    "FROM search_documents WHERE content_type = :ctype"
                ),
                {"ctype": content_type},
            ).mappings().all()
        else:
            rows = db.execute(
                text(
                    "SELECT id, title, content, content_type, url, metadata_json "
                    "FROM search_documents"
                )
            ).mappings().all()
    except Exception as exc:
        logger.warning("SQL source search failed: %s", exc)
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        title = (row.get("title") or "").lower()
        content = (row.get("content") or "").lower()
        blob = f"{title} {content}"
        if tokens:
            hits = sum(1 for t in tokens if t in blob)
            if hits == 0:
                continue
            # Prefer title matches
            title_hits = sum(1 for t in tokens if t in title)
            score = hits + title_hits * 1.5
        else:
            score = 0.5

        meta: dict[str, Any] = {}
        try:
            meta = json.loads(row.get("metadata_json") or "{}")
        except Exception:
            meta = {}

        scored.append(
            (
                score,
                {
                    "id": row.get("id") or "",
                    "title": row.get("title") or "",
                    "snippet": ((row.get("content") or "")[:220]),
                    "content_type": row.get("content_type") or "item",
                    "url": row.get("url") or "",
                    "metadata": meta,
                    "score": float(score),
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[: max(top_k, 1)]]
