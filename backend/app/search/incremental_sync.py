"""
Incremental push indexing driven by schema catalog + watermarks.

NEW/UPDATED → build canonical doc; re-embed only when search_text_hash changes.
DELETED → handled by index_purge / explicit delete keys.
UNCHANGED → no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.search.catalog.builder import build_canonical_document
from app.search.catalog.loader import list_entities
from app.search.sync_state import get_watermark, set_watermark

logger = logging.getLogger(__name__)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _max_watermark(values: list[Any]) -> Optional[str]:
    stamps: list[datetime] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, datetime):
            stamps.append(v)
        else:
            parsed = _parse_ts(str(v))
            if parsed:
                stamps.append(parsed)
    if not stamps:
        return None
    return max(stamps).isoformat()


def sync_entity_incremental(
    db: Session,
    entity_name: str,
    *,
    embed: bool = True,
    full: bool = False,
) -> dict[str, Any]:
    """Delta-sync one catalog entity from SQL → Azure AI Search."""
    from app.search.indexer import index_documents
    from app.search.catalog.loader import get_entity

    entity = get_entity(entity_name)
    if not entity or entity.source != "buildtrack":
        return {"entity": entity_name, "skipped": True, "reason": "not buildtrack orm"}

    watermark = None if full or not settings.SEARCH_INCREMENTAL_SYNC else get_watermark(
        db, entity.source, entity.entity
    )
    wm_dt = _parse_ts(watermark)

    rows: list[Any] = []
    if entity.entity == "project":
        from app.models.project import Project

        q = db.query(Project).options(joinedload(Project.project_manager))
        if wm_dt is not None and entity.updated_at_field:
            q = q.filter(getattr(Project, entity.updated_at_field) > wm_dt)
        rows = q.all()
    elif entity.entity == "task":
        from app.models.task import Task

        q = db.query(Task).options(joinedload(Task.project), joinedload(Task.assignee))
        if wm_dt is not None and entity.updated_at_field:
            q = q.filter(getattr(Task, entity.updated_at_field) > wm_dt)
        rows = q.all()
    elif entity.entity == "document":
        from app.models.document import Document

        q = db.query(Document).options(joinedload(Document.project), joinedload(Document.uploader))
        if wm_dt is not None and entity.updated_at_field:
            q = q.filter(getattr(Document, entity.updated_at_field) > wm_dt)
        rows = q.all()
    elif entity.entity == "drawing":
        from app.models.operational import EngineeringDrawing

        q = db.query(EngineeringDrawing)
        if wm_dt is not None and entity.updated_at_field:
            q = q.filter(getattr(EngineeringDrawing, entity.updated_at_field) > wm_dt)
        rows = q.all()
    else:
        return {"entity": entity_name, "skipped": True, "reason": "unsupported"}

    docs: list[dict[str, Any]] = []
    stamps: list[Any] = []
    for row in rows:
        doc = build_canonical_document(entity.entity, row)
        if doc:
            docs.append(doc)
        if entity.updated_at_field:
            stamps.append(getattr(row, entity.updated_at_field, None))

    stats = {"changed": len(docs), "watermark_before": watermark}
    if docs:
        result = index_documents(docs, embed=embed and entity.embedding_enabled)
        stats.update(result)
    else:
        stats.update({"ok": 0, "failed": 0})

    new_wm = _max_watermark(stamps) or watermark or datetime.utcnow().isoformat()
    set_watermark(db, entity.source, entity.entity, new_wm, stats=stats)

    try:
        from app.search.metrics import record_sync

        record_sync(changed=len(docs))
    except Exception:
        pass

    logger.info(
        "Incremental sync %s: %s docs (wm %s → %s)",
        entity.entity,
        len(docs),
        watermark,
        new_wm,
    )
    return {"entity": entity.entity, **stats}


def sync_buildtrack_incremental(
    db: Session,
    *,
    embed: bool = True,
    full: bool = False,
) -> dict[str, Any]:
    results = []
    for ent in list_entities(source="buildtrack"):
        if ent.entity in {"project", "task", "document", "drawing"}:
            results.append(
                sync_entity_incremental(db, ent.entity, embed=embed, full=full)
            )
    return {
        "mode": "full" if full or not settings.SEARCH_INCREMENTAL_SYNC else "incremental",
        "entities": results,
        "total_changed": sum(int(r.get("changed") or 0) for r in results),
    }
