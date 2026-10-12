"""Build slim canonical Azure AI Search documents from catalog + ORM/dict rows."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from app.search.catalog.loader import get_entity, get_entity_by_type
from app.search.catalog.models import EntityCatalog

logger = logging.getLogger(__name__)


def _as_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    out: dict[str, Any] = {}
    for key in getattr(row, "__table__", None).columns.keys() if hasattr(getattr(row, "__table__", None), "columns") else []:
        out[key] = getattr(row, key, None)
    if out:
        # relationships commonly needed for titles
        for rel in ("project_manager", "project", "assignee", "uploader"):
            if hasattr(row, rel):
                try:
                    out[rel] = getattr(row, rel)
                except Exception:
                    pass
        return out
    # Fallback: public attrs
    for key, val in vars(row).items():
        if not key.startswith("_"):
            out[key] = val
    return out


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return str(value)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def search_text_hash(search_text: str) -> str:
    return hashlib.sha256((search_text or "").encode("utf-8")).hexdigest()


def build_search_text(entity: EntityCatalog, data: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in entity.search_fields:
        val = data.get(field)
        text = _stringify(val).strip()
        if text:
            parts.append(text)
    # Light structured context for keyword match (not embedded as separate vectors)
    for field in ("status", "location", "discipline", "drawing_no"):
        if field in entity.filter_fields or field in entity.search_fields:
            val = _stringify(data.get(field)).strip()
            if val and val not in parts:
                parts.append(f"{field}: {val}")
    return " ".join(parts).strip()


def _title(entity: EntityCatalog, data: dict[str, Any]) -> str:
    if entity.title_field and data.get(entity.title_field):
        return _stringify(data[entity.title_field])
    if data.get("title"):
        return _stringify(data["title"])
    if data.get("name"):
        return _stringify(data["name"])
    return f"{entity.entity_type}-{data.get(entity.id_field, '')}"


def _url(entity: EntityCatalog, data: dict[str, Any]) -> str:
    if not entity.url_template:
        return ""
    try:
        return entity.url_template.format(**{entity.id_field: data.get(entity.id_field), "id": data.get(entity.id_field)})
    except Exception:
        return entity.url_template


def _filter_metadata(entity: EntityCatalog, data: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for field in entity.filter_fields:
        if field in data and data[field] is not None:
            meta[field] = _stringify(data[field]) if not isinstance(data[field], (int, float, bool)) else data[field]
    for field in entity.acl_fields:
        if field == "project_id" and data.get("project_id") is not None:
            meta["project_id"] = data.get("project_id")
        elif field == "project_id" and entity.entity_type == "project" and data.get("id") is not None:
            meta["project_id"] = data.get("id")
    meta["entity"] = entity.entity
    meta["source"] = entity.source
    return meta


def build_canonical_document(
    entity_name: str,
    row: Any,
    *,
    source_database: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Produce a slim discovery document:
    - title + search_text (Tier 1)
    - filterable top-level fields (Tier 2)
    - metadata JSON for backward-compatible consumers
    - search_text_hash for incremental embedding
    Does NOT include Tier 3 / sql_only fields.
    """
    entity = get_entity(entity_name) or get_entity_by_type(entity_name)
    if not entity:
        logger.warning("No catalog entity for %s", entity_name)
        return None

    data = _as_dict(row)
    rid = data.get(entity.id_field)
    if rid is None:
        return None

    text = build_search_text(entity, data)
    # Documents: never put body_text into discovery content when index_body_text is false
    if entity.entity_type == "document" and not entity.index_body_text:
        data = {k: v for k, v in data.items() if k != "body_text"}

    meta = _filter_metadata(entity, data)
    source = source_database or entity.source
    doc_id = f"{entity.entity_type}-{rid}"
    updated = data.get(entity.updated_at_field) if entity.updated_at_field else None

    doc: dict[str, Any] = {
        "id": doc_id,
        "title": _title(entity, data),
        # Keep legacy `content` populated from search_text for existing semantic config
        "content": text[:8000],
        "content_type": entity.entity_type,
        "url": _url(entity, data),
        "metadata": json.dumps(meta),
        # Production discovery fields
        "entity_id": str(rid),
        "entity_type": entity.entity_type,
        "source_database": source,
        "search_text": text[:8000],
        "search_text_hash": search_text_hash(text),
        "updated_at": _stringify(updated) if updated else None,
        "embedding_enabled": entity.embedding_enabled,
    }

    # Promote common Tier 2 fields for OData filters
    status = data.get("status")
    if status is not None:
        doc["record_status"] = _stringify(status)
        doc["status"] = _stringify(status)
    if data.get("location"):
        doc["location"] = _stringify(data["location"])
    if data.get("progress") is not None:
        try:
            doc["progress_pct"] = int(data["progress"])
        except (TypeError, ValueError):
            pass
    project_id = data.get("project_id")
    if project_id is None and entity.entity_type == "project":
        project_id = rid
    if project_id is not None:
        doc["project_id"] = str(project_id)

    return doc


def build_from_orm(entity_name: str, row: Any) -> Optional[dict[str, Any]]:
    return build_canonical_document(entity_name, row)
