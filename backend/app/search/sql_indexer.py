"""
Keep Azure AI Search in sync with the primary SQL database.

Two modes:
  - pull (Azure SQL only): managed Azure SQL Indexer reaches into the DB
  - push (local / non-Azure SQL): app reads SQL and uploads documents

Local SQL Server cannot be reached by the cloud indexer, so push is automatic
when DATABASE_URL is not an Azure SQL host (*.database.windows.net).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

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


def _database_host() -> str:
    url = settings.DATABASE_URL or ""
    # mssql+pyodbc://user:pass@host:1433/db?...
    try:
        # SQLAlchemy URLs sometimes lack a scheme SQLAlchemy understands for urlparse
        # after the driver; normalize to something urlparse can read.
        normalized = url.replace("mssql+pyodbc://", "mssql://", 1)
        parsed = urlparse(normalized)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def uses_push_indexing() -> bool:
    """True when the managed Azure SQL indexer cannot reach this database."""
    host = _database_host()
    if not host:
        return True
    return not host.endswith(".database.windows.net")


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
    """Sync the primary search index now (pull indexer or push from SQL)."""
    global _last_trigger_at
    now = time.time()
    with _trigger_lock:
        if now - _last_trigger_at < MIN_TRIGGER_INTERVAL_SEC:
            logger.debug("Search index sync skipped (debounced)")
            return
        _last_trigger_at = now

    if uses_push_indexing():
        from app.search.sql_push_indexer import sync_primary_db_to_azure_search

        stats = sync_primary_db_to_azure_search(embed=True)
        logger.info("Push index sync: %s", stats.get("message"))
        return

    client = _indexer_client()
    client.run_indexer(INDEXER_NAME)
    logger.info("SQL indexer '%s' run triggered", INDEXER_NAME)
    from app.search.index_reader import clear_index_cache

    clear_index_cache()


def trigger_sql_indexer_async() -> None:
    """Fire-and-forget index sync (e.g. after document upload to SQL)."""

    def _run():
        try:
            trigger_sql_indexer_run()
        except Exception as exc:
            logger.warning("Background search index sync failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="sql-indexer-trigger").start()


def get_sql_indexer_status() -> dict[str, Any]:
    """Return indexer / push-mode status for diagnostics."""
    if uses_push_indexing():
        return {
            "indexer": INDEXER_NAME,
            "mode": "push",
            "status": "push-from-app",
            "schedule": "on write (debounced) + manual sync",
            "source": "primary SQL via app push (local/non-Azure database)",
            "database_host": _database_host() or "(unknown)",
        }
    try:
        client = _indexer_client()
        status = client.get_indexer_status(INDEXER_NAME)
        last = status.last_result
        return {
            "indexer": INDEXER_NAME,
            "mode": "pull",
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
            "mode": "pull",
            "status": "unknown",
            "error": str(exc),
        }


def wait_for_sql_indexer(timeout_sec: int = 600) -> Optional[dict[str, Any]]:
    """Block until indexer finishes or timeout. Used by setup script only."""
    if uses_push_indexing():
        from app.search.sql_push_indexer import sync_primary_db_to_azure_search

        sync_primary_db_to_azure_search(embed=True)
        return get_sql_indexer_status()

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
