"""
Read application content from Azure AI Search — the only supported read path.

Data flow: Azure SQL (vw_global_search_documents) → SQL Indexer → Azure AI Search → here.
Do not query SQL tables directly for page/display data.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from app.search.indexer import get_search_client

logger = logging.getLogger(__name__)

_SELECT = ["id", "title", "content", "content_type", "url", "metadata"]
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_doc_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 300
_DOC_CACHE_TTL = 300


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _row(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc.get("id", ""),
        "title": doc.get("title", ""),
        "content": doc.get("content", "") or "",
        "content_type": doc.get("content_type", ""),
        "url": doc.get("url", ""),
        "metadata": _parse_metadata(doc.get("metadata")),
    }


def _client_or_raise():
    client = get_search_client()
    if not client:
        raise RuntimeError(
            "Azure AI Search is not configured — page data is loaded from the SQL indexer index only"
        )
    return client


def list_indexed(
    content_type: Optional[str] = None,
    *,
    id_prefix: Optional[str] = None,
    top: int = 500,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """List documents from Azure AI Search (wildcard query, optional filter)."""
    return filter_indexed(content_type=content_type, id_prefix=id_prefix, top=top, use_cache=use_cache)


def filter_indexed(
    *,
    content_types: Optional[list[str]] = None,
    content_type: Optional[str] = None,
    progress: Optional[int] = None,
    status: Optional[str] = None,
    id_prefix: Optional[str] = None,
    top: int = 500,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Exact filter query against Azure AI Search filterable fields.
    Uses OData filters — returns ALL matches up to `top`, not relevance-ranked subset.
    """
    types = content_types or ([content_type] if content_type else [])
    cache_key = f"filter|{'|'.join(types)}|{progress}|{status}|{id_prefix}|{top}"
    if use_cache and cache_key in _cache:
        ts, rows = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return rows

    client = _client_or_raise()
    clauses: list[str] = []
    if len(types) == 1:
        clauses.append(f"content_type eq '{types[0]}'")
    elif len(types) > 1:
        type_filter = " or ".join(f"content_type eq '{t}'" for t in types)
        clauses.append(f"({type_filter})")
    if progress is not None:
        clauses.append(f"progress_pct eq {int(progress)}")
    # Status matched in Python — values vary (In Progress vs in_progress)

    kwargs: dict[str, Any] = {
        "search_text": "*",
        "top": top,
        "select": _SELECT,
        "include_total_count": False,
    }
    if clauses:
        kwargs["filter"] = " and ".join(clauses)

    rows: list[dict[str, Any]] = []
    try:
        for doc in client.search(**kwargs):
            item = _row(doc)
            if id_prefix and not item["id"].startswith(id_prefix):
                continue
            if status is not None:
                from app.search.structured_filters import _status_matches
                meta_status = item.get("metadata", {}).get("status") or doc.get("record_status")
                if not _status_matches(meta_status, status):
                    continue
            rows.append(item)
    except Exception as exc:
        err = str(exc)
        if progress is not None and "progress_pct" in err:
            logger.debug("progress_pct not in index yet — using metadata scan fallback")
        else:
            logger.warning("OData filter failed (%s), falling back to scan: %s", cache_key, exc)
        rows = _scan_and_filter(types, progress, status, id_prefix, top)

    rows.sort(key=lambda r: r.get("title", ""))
    if use_cache:
        _cache[cache_key] = (time.time(), rows)
    return rows


def _scan_and_filter(
    types: list[str],
    progress: Optional[int],
    status: Optional[str],
    id_prefix: Optional[str],
    top: int,
) -> list[dict[str, Any]]:
    """Fallback when filterable index fields are not yet populated."""
    from app.search.structured_filters import _meta_int, _status_matches

    scan_types = types or [None]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ctype in scan_types:
        for doc in _list_all_raw(ctype, top):
            rid = doc.get("id", "")
            if not rid or rid in seen:
                continue
            meta = doc.get("metadata") or {}
            if progress is not None and _meta_int(meta.get("progress")) != progress:
                continue
            if status is not None and not _status_matches(meta.get("status"), status):
                continue
            if id_prefix and not rid.startswith(id_prefix):
                continue
            seen.add(rid)
            rows.append(doc)
            if len(rows) >= top:
                break
    return rows


def _list_all_raw(content_type: Optional[str], top: int) -> list[dict[str, Any]]:
    client = _client_or_raise()
    kwargs: dict[str, Any] = {
        "search_text": "*",
        "top": top,
        "select": _SELECT,
    }
    if content_type:
        kwargs["filter"] = f"content_type eq '{content_type}'"
    return [_row(doc) for doc in client.search(**kwargs)]


def get_indexed(item_id: str) -> Optional[dict[str, Any]]:
    now = time.time()
    cached = _doc_cache.get(item_id)
    if cached and now - cached[0] < _DOC_CACHE_TTL:
        return cached[1]
    client = _client_or_raise()
    try:
        doc = client.get_document(key=item_id)
        row = _row(doc)
        _doc_cache[item_id] = (now, row)
        return row
    except Exception:
        return None


def get_kpi_item(item_id: str) -> Optional[dict[str, Any]]:
    return get_indexed(item_id)


def clear_index_cache() -> None:
    _cache.clear()
    _doc_cache.clear()
