"""Watermark table for incremental search indexing."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.database import Base

logger = logging.getLogger(__name__)


class SearchSyncState(Base):
    __tablename__ = "search_sync_state"
    __table_args__ = (
        UniqueConstraint("source", "entity", name="uq_search_sync_source_entity"),
    )

    id = Column(String(64), primary_key=True)
    source = Column(String(64), nullable=False, index=True)
    entity = Column(String(64), nullable=False, index=True)
    watermark = Column(String(64), nullable=True)  # ISO timestamp or version
    last_run_at = Column(DateTime(timezone=True), server_default=func.now())
    stats_json = Column(Text, nullable=True)


def ensure_sync_table(db: Session) -> None:
    try:
        Bind = db.get_bind()
        SearchSyncState.__table__.create(bind=Bind, checkfirst=True)
    except Exception as exc:
        logger.debug("search_sync_state ensure: %s", exc)


def _row_id(source: str, entity: str) -> str:
    return f"{source}:{entity}"


def get_watermark(db: Session, source: str, entity: str) -> Optional[str]:
    ensure_sync_table(db)
    row = (
        db.query(SearchSyncState)
        .filter(SearchSyncState.id == _row_id(source, entity))
        .first()
    )
    return row.watermark if row else None


def set_watermark(
    db: Session,
    source: str,
    entity: str,
    watermark: str,
    stats: Optional[dict[str, Any]] = None,
) -> None:
    ensure_sync_table(db)
    rid = _row_id(source, entity)
    row = db.query(SearchSyncState).filter(SearchSyncState.id == rid).first()
    if row is None:
        row = SearchSyncState(id=rid, source=source, entity=entity)
        db.add(row)
    row.watermark = watermark
    row.last_run_at = datetime.now(timezone.utc)
    row.stats_json = json.dumps(stats or {})
    db.commit()


def list_sync_states(db: Session) -> list[dict[str, Any]]:
    ensure_sync_table(db)
    rows = db.query(SearchSyncState).all()
    out = []
    for r in rows:
        lag = None
        if r.last_run_at:
            lag = (datetime.now(timezone.utc) - r.last_run_at.replace(tzinfo=timezone.utc)).total_seconds()
        out.append(
            {
                "source": r.source,
                "entity": r.entity,
                "watermark": r.watermark,
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                "lag_seconds": lag,
                "stats": json.loads(r.stats_json or "{}"),
            }
        )
    return out
