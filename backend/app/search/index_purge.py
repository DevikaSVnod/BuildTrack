"""Remove stale Azure AI Search documents that no longer exist in SQL."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from sqlalchemy import text

from app.core.database import engine
from app.search.indexer import get_search_client
from app.search.sql_indexer import SQL_VIEW, trigger_sql_indexer_run

logger = logging.getLogger(__name__)

_purge_lock = threading.Lock()
_last_purge_at: float = 0
MIN_PURGE_INTERVAL_SEC = 30


def _valid_ids_from_sql() -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT id FROM dbo.{SQL_VIEW}"))
        return {str(row[0]) for row in rows}


def _all_index_ids(client) -> list[str]:
    ids: list[str] = []
    results = client.search(search_text="*", top=1000, select=["id"])
    for batch in results.by_page():
        for doc in batch:
            doc_id = doc.get("id")
            if doc_id:
                ids.append(str(doc_id))
    return ids


def delete_index_ids(index_ids: list[str]) -> int:
    """Delete specific keys from the SQL search index (e.g. document-13)."""
    if not index_ids:
        return 0
    client = get_search_client()
    if not client:
        return 0
    unique = sorted({str(i) for i in index_ids if i})
    batch_size = 500
    deleted = 0
    for i in range(0, len(unique), batch_size):
        chunk = unique[i : i + batch_size]
        client.delete_documents([{"id": doc_id} for doc_id in chunk])
        deleted += len(chunk)
    if deleted:
        logger.info("Deleted %s search index doc(s): %s", deleted, unique[:5])
        from app.search.index_reader import clear_index_cache
        from app.search.retrieval import _search_cache
        from app.search.answer import _answer_cache

        clear_index_cache()
        _search_cache.clear()
        _answer_cache.clear()
    return deleted


def delete_sql_backed_row(content_type: str, row_id: int) -> int:
    """Remove one SQL-backed search document immediately after delete."""
    prefix = (content_type or "").strip().lower()
    if prefix not in ("document", "drawing", "project", "task", "handover", "safety"):
        return 0
    return delete_index_ids([f"{prefix}-{row_id}"])


def purge_stale_search_index(*, dry_run: bool = False, reindex: bool = True) -> dict[str, Any]:
    """
    Delete search index documents whose id is not in vw_global_search_documents.
  Returns summary stats.
    """
    client = get_search_client()
    if not client:
        return {"deleted": 0, "orphans": 0, "error": "search not configured"}

    valid = _valid_ids_from_sql()
    indexed = _all_index_ids(client)
    orphans = sorted(set(indexed) - valid)

    result: dict[str, Any] = {
        "sql_rows": len(valid),
        "index_docs": len(indexed),
        "orphans": len(orphans),
        "deleted": 0,
        "dry_run": dry_run,
    }

    if not orphans or dry_run:
        return result

    batch_size = 500
    deleted = 0
    for i in range(0, len(orphans), batch_size):
        chunk = orphans[i : i + batch_size]
        client.delete_documents([{"id": doc_id} for doc_id in chunk])
        deleted += len(chunk)

    result["deleted"] = deleted
    logger.info("Purged %s stale search index doc(s)", deleted)

    from app.search.index_reader import clear_index_cache
    from app.search.retrieval import _search_cache
    from app.search.answer import _answer_cache

    clear_index_cache()
    _search_cache.clear()
    _answer_cache.clear()

    if reindex:
        try:
            trigger_sql_indexer_run()
        except Exception as exc:
            logger.warning("SQL indexer trigger after purge failed: %s", exc)

    return result


def purge_stale_search_index_async(*, force: bool = False) -> None:
    """Background full orphan purge (debounced)."""

    def _run():
        global _last_purge_at
        now = time.time()
        with _purge_lock:
            if not force and now - _last_purge_at < MIN_PURGE_INTERVAL_SEC:
                logger.debug("Stale index purge skipped (debounced)")
                return
            _last_purge_at = now
        try:
            stats = purge_stale_search_index(reindex=False)
            if stats.get("deleted"):
                logger.info("Background purge removed %s stale index doc(s)", stats["deleted"])
        except Exception as exc:
            logger.warning("Background stale index purge failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="search-index-purge").start()


def purge_after_sql_delete(content_type: str, row_id: int) -> None:
    """
    After a SQL row is deleted: remove its search key immediately, then debounced full purge.
    """
    try:
        delete_sql_backed_row(content_type, row_id)
    except Exception as exc:
        logger.warning("Immediate index delete failed for %s-%s: %s", content_type, row_id, exc)
    purge_stale_search_index_async()
