"""
Azure AI Search SQL Indexer — the ONLY path that writes to the search index.

Data flow:
  Azure SQL (vw_global_search_documents) → SQL Indexer → Azure AI Search

Do not call index_documents() from application code.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

INDEXER_NAME = "buildtrack-sql-indexer"
DS_NAME = "buildtrack-sql-datasource"
SKILLSET_NAME = "buildtrack-embedding-skillset"
SQL_VIEW = "vw_global_search_documents"
# Expose filterable fields extracted from metadata JSON (one-time indexer re-run required).
SQL_QUERY = f"""
SELECT id, title, content, content_type, url, metadata,
  TRY_CAST(JSON_VALUE(metadata, '$.progress') AS INT) AS progress_pct,
  JSON_VALUE(metadata, '$.status') AS record_status
FROM dbo.{SQL_VIEW}
"""

_trigger_lock = threading.Lock()
_last_trigger_at: float = 0
MIN_TRIGGER_INTERVAL_SEC = 60  # debounce rapid upload bursts


def _indexer_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexerClient

    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        raise RuntimeError("Azure AI Search is not configured")
    return SearchIndexerClient(
        settings.AZURE_SEARCH_ENDPOINT,
        AzureKeyCredential(settings.AZURE_SEARCH_KEY),
    )


def trigger_sql_indexer_run() -> None:
    """Ask Azure to run the SQL indexer now (non-blocking)."""
    global _last_trigger_at
    now = time.time()
    with _trigger_lock:
        if now - _last_trigger_at < MIN_TRIGGER_INTERVAL_SEC:
            logger.debug("SQL indexer trigger skipped (debounced)")
            return
        _last_trigger_at = now
    client = _indexer_client()
    client.run_indexer(INDEXER_NAME)
    logger.info("SQL indexer '%s' run triggered", INDEXER_NAME)
    from app.search.index_reader import clear_index_cache
    clear_index_cache()


def trigger_sql_indexer_async() -> None:
    """Fire-and-forget SQL indexer run (e.g. after document upload to SQL)."""

    def _run():
        try:
            trigger_sql_indexer_run()
        except Exception as exc:
            logger.warning("Background SQL indexer trigger failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="sql-indexer-trigger").start()


def get_sql_indexer_status() -> dict[str, Any]:
    """Return Azure SQL indexer execution status."""
    try:
        client = _indexer_client()
        status = client.get_indexer_status(INDEXER_NAME)
        last = status.last_result
        return {
            "indexer": INDEXER_NAME,
            "status": str(status.status),
            "last_result": str(last.status) if last else None,
            "last_item_count": last.item_count if last else 0,
            "last_error_count": len(last.errors) if last and last.errors else 0,
            "last_errors": [e.error_message for e in (last.errors or [])[:3]] if last else [],
            "schedule": "every 15 minutes (PT15M)",
            "source": f"Azure SQL view {SQL_VIEW}",
        }
    except Exception as exc:
        return {
            "indexer": INDEXER_NAME,
            "status": "unknown",
            "error": str(exc),
        }


def wait_for_sql_indexer(timeout_sec: int = 600) -> Optional[dict[str, Any]]:
    """Block until indexer finishes or timeout. Used by setup script only."""
    client = _indexer_client()
    client.run_indexer(INDEXER_NAME)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(10)
        status = client.get_indexer_status(INDEXER_NAME)
        last = status.last_result
        state = str(status.status)
        if state in ("running", "reset"):
            continue
        if last and str(last.status) in ("success", "transientFailure", "failed"):
            return get_sql_indexer_status()
    return get_sql_indexer_status()
