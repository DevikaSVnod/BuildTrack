"""Trigger Azure AI Search blob/RAG indexers after file uploads."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_trigger_lock = threading.Lock()
_last_trigger_at: float = 0
MIN_TRIGGER_INTERVAL_SEC = 120


def _indexer_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexerClient

    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        raise RuntimeError("Azure AI Search is not configured")
    return SearchIndexerClient(
        settings.AZURE_SEARCH_ENDPOINT,
        AzureKeyCredential(settings.AZURE_SEARCH_KEY),
    )


def list_blob_indexer_names() -> list[str]:
    client = _indexer_client()
    names: list[str] = []
    for indexer in client.get_indexers():
        lower = indexer.name.lower()
        if "blob" in lower or "rag" in lower:
            names.append(indexer.name)
    return names


def trigger_blob_indexer_run() -> list[str]:
    """Run all blob/RAG indexers. Returns names triggered."""
    global _last_trigger_at
    now = time.time()
    with _trigger_lock:
        if now - _last_trigger_at < MIN_TRIGGER_INTERVAL_SEC:
            logger.debug("Blob indexer trigger skipped (debounced)")
            return []
        _last_trigger_at = now

    client = _indexer_client()
    triggered: list[str] = []
    for name in list_blob_indexer_names():
        client.run_indexer(name)
        triggered.append(name)
        logger.info("Blob/RAG indexer '%s' run triggered", name)
    return triggered


def trigger_blob_indexer_async() -> None:
    def _run():
        try:
            trigger_blob_indexer_run()
        except Exception as exc:
            logger.warning("Background blob indexer trigger failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="blob-indexer-trigger").start()


def get_blob_indexer_status() -> dict[str, Any]:
    try:
        client = _indexer_client()
        names = list_blob_indexer_names()
        if not names:
            return {"configured": False, "indexers": []}
        statuses = []
        for name in names:
            status = client.get_indexer_status(name)
            last = status.last_result
            statuses.append(
                {
                    "name": name,
                    "status": str(status.status),
                    "last_result": str(last.status) if last else None,
                    "items_processed": last.item_count if last else None,
                }
            )
        return {"configured": True, "indexers": statuses}
    except Exception as exc:
        return {"configured": False, "error": str(exc)}
