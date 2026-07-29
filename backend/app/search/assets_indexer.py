"""
Push Site Assets & Procurement Azure SQL rows into Azure AI Search.

Multi-DB Global Search runs hybrid Azure search against:
  - buildtrack-index         (primary Azure SQL: buildtrack)
  - buildtrack-assets-index  (satellite Azure SQL: buildtrack_assets)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.data_sources import ensure_assets_database
from app.search.indexer import ensure_index_exists, get_search_client, index_documents

logger = logging.getLogger(__name__)


def assets_index_name() -> str:
    return settings.AZURE_SEARCH_ASSETS_INDEX or "buildtrack-assets-index"


def _assets_sql_url() -> str:
    from scripts.setup_assets_db import resolve_assets_database_url

    return resolve_assets_database_url()


def load_assets_search_docs() -> list[dict[str, Any]]:
    """Read flattened search_documents from Azure SQL buildtrack_assets."""
    from scripts.setup_assets_db import create_mssql_engine

    ensure_assets_database()
    url = _assets_sql_url()
    engine = create_mssql_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        rows = db.execute(
            text(
                "SELECT id, title, content, content_type, url, metadata_json "
                "FROM search_documents"
            )
        ).mappings().all()
    finally:
        db.close()
        engine.dispose()

    docs: list[dict[str, Any]] = []
    for row in rows:
        meta_raw = row.get("metadata_json") or "{}"
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except Exception:
            meta = {}
        meta = dict(meta)
        meta["database_id"] = "assets"
        meta["database_label"] = "Site Assets & Procurement"
        meta["source_db"] = "buildtrack_assets"
        docs.append(
            {
                "id": row["id"],
                "title": row["title"] or "",
                "content": row["content"] or "",
                "content_type": row["content_type"] or "item",
                "url": row["url"] or "",
                "metadata": json.dumps(meta, ensure_ascii=False),
            }
        )
    return docs


def assets_index_doc_count() -> Optional[int]:
    client = get_search_client(assets_index_name())
    if not client:
        return None
    try:
        return int(client.get_document_count())
    except Exception as exc:
        logger.warning("Could not read assets index doc count: %s", exc)
        return None


def sync_assets_to_azure_search(*, embed: bool = True) -> dict[str, Any]:
    """Ensure assets index exists and upload all assets search_documents."""
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        raise RuntimeError("Azure Search is not configured (AZURE_SEARCH_ENDPOINT / KEY)")

    index = assets_index_name()
    if not ensure_index_exists(index):
        raise RuntimeError(f"Failed to create/update Azure Search index {index}")

    docs = load_assets_search_docs()
    if not docs:
        return {
            "index": index,
            "documents_loaded": 0,
            "uploaded_ok": 0,
            "uploaded_failed": 0,
            "message": "Assets DB has no search_documents rows",
        }

    result = index_documents(docs, embed=embed, index_name=index)
    count = assets_index_doc_count()
    return {
        "index": index,
        "sql_database": "buildtrack_assets",
        "documents_loaded": len(docs),
        "uploaded_ok": result.get("ok", 0),
        "uploaded_failed": result.get("failed", 0),
        "index_doc_count": count,
        "message": (
            f"Synced {result.get('ok', 0)} docs from Azure SQL 'buildtrack_assets' "
            f"into Azure AI Search index '{index}'"
        ),
    }
