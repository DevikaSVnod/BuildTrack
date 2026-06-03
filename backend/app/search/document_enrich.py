"""Refresh document search hits from Azure AI Search (SQL indexer output)."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.search.index_reader import get_indexed


def enrich_document_results(_db, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-load document hits from the search index (no direct SQL reads)."""
    enriched: List[Dict[str, Any]] = []
    for item in results:
        if item.get("content_type") != "document":
            enriched.append(item)
            continue
        rid = item.get("id", "")
        m = re.match(r"document-(\d+)", rid)
        if not m and isinstance(item.get("metadata"), dict):
            did = item["metadata"].get("doc_id")
            rid = f"document-{did}" if did is not None else rid
        fresh = get_indexed(rid) if rid else None
        if not fresh:
            enriched.append(item)
            continue
        meta = fresh.get("metadata") or {}
        patched = dict(item)
        patched["metadata"] = meta
        patched["title"] = fresh.get("title", item.get("title", ""))
        patched["snippet"] = (fresh.get("content") or "")[:220]
        enriched.append(patched)
    return enriched
