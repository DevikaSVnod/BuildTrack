"""
Read application content from Azure AI Search (POC page-read path).

Production: prefer SQL hydration (`SEARCH_HYDRATE_FROM_SQL`) via content_service /
hydrate.py. Search remains discovery-only; this module is legacy for types not yet
migrated off the index.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Optional

from app.search.indexer import get_search_client

logger = logging.getLogger(__name__)

_SELECT = ["id", "title", "content", "content_type", "url", "metadata"]
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
# A cached None means "confirmed absent from the index" — without it, hits whose
# id is not in the index are re-requested on every enrichment pass.
_doc_cache: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}
_CACHE_TTL = 300
_DOC_CACHE_TTL = 300

# One lock per cache key so parallel callers (the multi-database fan-out asks
# for the same listings at once) share a single index read instead of racing.
_key_locks: dict[str, Lock] = {}
_key_locks_guard = Lock()

_doc_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="index-read")


def _key_lock(key: str) -> Lock:
    with _key_locks_guard:
        lock = _key_locks.get(key)
        if lock is None:
            lock = Lock()
            _key_locks[key] = lock
        return lock


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


def _client_or_raise(search_index: Optional[str] = None):
    client = get_search_client(search_index)
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
    project_manager: Optional[str] = None,
    id_prefix: Optional[str] = None,
    search_index: Optional[str] = None,
    top: int = 500,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Exact filter query against Azure AI Search filterable fields.
    Uses OData filters — returns ALL matches up to `top`, not relevance-ranked subset.
    """
    types = content_types or ([content_type] if content_type else [])
    cache_key = (
        f"filter|{'|'.join(types)}|{progress}|{status}|{project_manager}"
        f"|{id_prefix}|{search_index or ''}|{top}"
    )

    def _run() -> list[dict[str, Any]]:
        return _query_index(
            types,
            progress=progress,
            status=status,
            project_manager=project_manager,
            id_prefix=id_prefix,
            search_index=search_index,
            top=top,
            cache_key=cache_key,
        )

    def _cached() -> Optional[list[dict[str, Any]]]:
        entry = _cache.get(cache_key)
        if entry is not None and time.time() - entry[0] < _CACHE_TTL:
            return entry[1]
        return None

    if not use_cache:
        return _run()

    rows = _cached()
    if rows is not None:
        return rows

    with _key_lock(cache_key):
        rows = _cached()
        if rows is not None:
            return rows
        rows = _run()
        _cache[cache_key] = (time.time(), rows)
        return rows


def _query_index(
    types: list[str],
    *,
    progress: Optional[int],
    status: Optional[str],
    project_manager: Optional[str],
    id_prefix: Optional[str],
    search_index: Optional[str],
    top: int,
    cache_key: str,
) -> list[dict[str, Any]]:
    client = _client_or_raise(search_index)
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
            if project_manager is not None:
                from app.search.query_intel import person_name_matches
                if not person_name_matches(
                    item.get("metadata", {}).get("project_manager"), project_manager
                ):
                    continue
            rows.append(item)
    except Exception as exc:
        err = str(exc)
        if progress is not None and "progress_pct" in err:
            logger.debug("progress_pct not in index yet — using metadata scan fallback")
        else:
            logger.warning("OData filter failed (%s), falling back to scan: %s", cache_key, exc)
        rows = _scan_and_filter(
            types,
            progress=progress,
            status=status,
            project_manager=project_manager,
            id_prefix=id_prefix,
            search_index=search_index,
            top=top,
        )

    rows.sort(key=lambda r: r.get("title", ""))
    return rows


def _scan_and_filter(
    types: list[str],
    *,
    progress: Optional[int],
    status: Optional[str],
    project_manager: Optional[str],
    id_prefix: Optional[str],
    search_index: Optional[str],
    top: int,
) -> list[dict[str, Any]]:
    """Fallback when filterable index fields are not yet populated."""
    from app.search.query_intel import person_name_matches
    from app.search.structured_filters import _meta_int, _status_matches

    scan_types = types or [None]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ctype in scan_types:
        for doc in _list_all_raw(ctype, top, search_index=search_index):
            rid = doc.get("id", "")
            if not rid or rid in seen:
                continue
            meta = doc.get("metadata") or {}
            if progress is not None and _meta_int(meta.get("progress")) != progress:
                continue
            if status is not None and not _status_matches(meta.get("status"), status):
                continue
            if project_manager is not None and not person_name_matches(
                meta.get("project_manager"), project_manager
            ):
                continue
            if id_prefix and not rid.startswith(id_prefix):
                continue
            seen.add(rid)
            rows.append(doc)
            if len(rows) >= top:
                break
    return rows


def _list_all_raw(
    content_type: Optional[str],
    top: int,
    *,
    search_index: Optional[str] = None,
) -> list[dict[str, Any]]:
    client = _client_or_raise(search_index)
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
    if cached is not None and now - cached[0] < _DOC_CACHE_TTL:
        return cached[1]
    client = _client_or_raise()
    _, row, absent = _fetch_one_indexed(client, item_id)
    if row is not None:
        _doc_cache[item_id] = (now, row)
    elif absent:
        _doc_cache[item_id] = (now, None)
    return row


def get_indexed_many(item_ids: list[str]) -> dict[str, Optional[dict[str, Any]]]:
    """Look up several indexed rows at once, warming the per-id cache.

    The index key is not filterable, so these stay individual lookups — but
    issuing them concurrently turns a per-hit serial cost into one round trip.
    """
    now = time.time()
    found: dict[str, Optional[dict[str, Any]]] = {}
    wanted: list[str] = []
    for item_id in dict.fromkeys(i for i in item_ids if i):
        cached = _doc_cache.get(item_id)
        if cached is not None and now - cached[0] < _DOC_CACHE_TTL:
            if cached[1] is not None:
                found[item_id] = cached[1]
            continue
        wanted.append(item_id)
    if not wanted:
        return found

    client = get_search_client()
    if client is None:
        return found

    for item_id, row, absent in _doc_executor.map(
        lambda i: _fetch_one_indexed(client, i), wanted
    ):
        if row is not None:
            _doc_cache[item_id] = (now, row)
            found[item_id] = row
        elif absent:
            _doc_cache[item_id] = (now, None)
    return found


def _fetch_one_indexed(client, item_id: str) -> tuple[str, Optional[dict[str, Any]], bool]:
    """Returns (id, row, is_confirmed_absent). Transient errors are not cached."""
    from azure.core.exceptions import ResourceNotFoundError

    try:
        return item_id, _row(client.get_document(key=item_id)), False
    except ResourceNotFoundError:
        return item_id, None, True
    except Exception as exc:
        logger.debug("Index read failed for %s: %s", item_id, exc)
        return item_id, None, False


def get_kpi_item(item_id: str) -> Optional[dict[str, Any]]:
    return get_indexed(item_id)


def clear_index_cache() -> None:
    _cache.clear()
    _doc_cache.clear()
