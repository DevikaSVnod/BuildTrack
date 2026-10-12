"""Push schema catalog table docs into Azure AI Search (not row data)."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.core.config import settings
from app.core.space_databases import list_space_db_configs
from app.schema_catalog.models import DatabaseSnapshot, TableInfo
from app.schema_catalog.snapshot import (
    load_current_snapshot,
    refresh_space_schema_catalog,
)
from app.search.indexer import ensure_index_exists, get_search_client, index_documents

logger = logging.getLogger(__name__)


def schema_index_name() -> str:
    return settings.AZURE_SEARCH_SCHEMA_INDEX or "space-schema-index"


def _table_doc(snap: DatabaseSnapshot, table: TableInfo) -> dict[str, Any]:
    col_lines = [
        f"{c.name} ({c.data_type})"
        + (" PK" if c.is_primary_key else "")
        + (f" — {c.description}" if c.description else "")
        for c in table.columns
    ]
    fk_lines = [
        f"{fk.get('from_column')} -> {fk.get('to_table')}.{fk.get('to_column')}"
        for fk in (table.foreign_keys or [])
    ]
    hints = ", ".join(table.search_hints or [])
    content = "\n".join(
        [
            f"Database: {snap.database_name}",
            f"Source: {snap.source_id} ({snap.source_label})",
            f"Schema: {table.schema_name}",
            f"Table: {table.name}",
            f"Description: {table.description}",
            f"Search hints: {hints}",
            "Columns:",
            *col_lines[:80],
            "Foreign keys:",
            *(fk_lines[:40] or ["(none)"]),
        ]
    )
    meta = {
        "database_id": snap.source_id,
        "database_label": snap.source_label,
        "source_db": snap.database_name,
        "schema_name": table.schema_name,
        "table_name": table.name,
        "columns": [c.name for c in table.columns],
        "primary_keys": table.primary_keys,
        "foreign_keys": table.foreign_keys,
        "search_hints": table.search_hints,
        "schema_version": snap.version,
        "doc_kind": "schema_table",
    }
    return {
        "id": f"schema-{snap.source_id}-{table.schema_name}-{table.name}".lower(),
        "title": f"{snap.database_name}.{table.schema_name}.{table.name}",
        "content": content,
        "content_type": "schema_table",
        # Top-level filterable field (shared index schema)
        "source_database": snap.source_id,
        "url": f"/schema/{snap.source_id}/{table.schema_name}/{table.name}",
        "metadata": json.dumps(meta, ensure_ascii=False, default=str),
    }


def load_schema_search_docs(
    snapshot: Optional[DatabaseSnapshot] = None,
    *,
    source_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    if snapshot is not None:
        return [_table_doc(snapshot, t) for t in snapshot.tables]

    docs: list[dict[str, Any]] = []
    if source_id:
        snap = load_current_snapshot(source_id)
        if snap is None:
            raise RuntimeError(
                f"No schema snapshot for {source_id} — refresh catalog first"
            )
        return [_table_doc(snap, t) for t in snap.tables]

    for cfg in list_space_db_configs(enabled_only=True):
        snap = load_current_snapshot(cfg.source_id)
        if snap is None:
            logger.warning("Skipping %s — no schema snapshot", cfg.source_id)
            continue
        docs.extend(_table_doc(snap, t) for t in snap.tables)
    if not docs:
        raise RuntimeError("No schema snapshots — run refresh_space_schema_catalog first")
    return docs


def schema_index_doc_count() -> Optional[int]:
    client = get_search_client(schema_index_name())
    if not client:
        return None
    try:
        return int(client.get_document_count())
    except Exception as exc:
        logger.warning("Could not read schema index doc count: %s", exc)
        return None


def sync_schema_catalog_to_azure_search(
    *,
    embed: bool = True,
    source_id: Optional[str] = None,
) -> dict[str, Any]:
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        raise RuntimeError("Azure Search is not configured")

    refresh = refresh_space_schema_catalog(source_id=source_id)

    index = schema_index_name()
    if not ensure_index_exists(index):
        raise RuntimeError(f"Failed to create/update schema index {index}")

    # Always upload all enabled Space schema docs so the shared index stays complete
    # even when refreshing a single source.
    docs = load_schema_search_docs()
    if not docs:
        return {
            "index": index,
            "documents_loaded": 0,
            "uploaded_ok": 0,
            "uploaded_failed": 0,
            "refresh": refresh,
            "message": "No schema tables to index",
        }

    result = index_documents(docs, embed=embed, index_name=index)
    count = schema_index_doc_count()
    sources_meta = refresh.get("sources") if isinstance(refresh, dict) else None
    if sources_meta is None and isinstance(refresh, dict):
        sources_meta = [refresh]
    return {
        "index": index,
        "sources": sources_meta,
        "tables": len(docs),
        "documents_loaded": len(docs),
        "uploaded_ok": result.get("ok", 0),
        "uploaded_failed": result.get("failed", 0),
        "index_doc_count": count,
        "refresh": refresh,
        "message": (
            f"Synced {result.get('ok', 0)} schema table docs into '{index}' "
            f"across {len(sources_meta or [])} Space DB(s)"
        ),
    }
