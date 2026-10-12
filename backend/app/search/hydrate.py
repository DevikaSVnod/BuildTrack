"""
Hydrate Top-K discovery hits from source SQL/API (authoritative records).

Azure AI Search returns ids; this module fetches full SoT rows.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.search.catalog.loader import get_entity_by_type
from app.search.catalog.models import EntityCatalog

logger = logging.getLogger(__name__)


def _parse_entity_id(hit_id: str, entity_type: str) -> Optional[str]:
    prefix = f"{entity_type}-"
    if hit_id.startswith(prefix):
        return hit_id[len(prefix) :]
    return hit_id or None


def _session_for_source(source: str, context: Optional[dict] = None) -> Optional[Session]:
    if context and source == "buildtrack" and context.get("db") is not None:
        return context["db"]
    try:
        from app.core.data_sources import get_source, session_for

        src = get_source(source)
        if not src:
            return None
        return session_for(src.id)
    except Exception as exc:
        logger.warning("Could not open session for source %s: %s", source, exc)
        return None


def _authorize_row(
    entity: EntityCatalog,
    row: dict[str, Any],
    user: Any,
) -> bool:
    """Re-check SoT authorization. POC: allow all authenticated users; filter by role later."""
    if not settings.SEARCH_SECURITY_TRIMMING:
        return True
    if user is None:
        return True
    # Admin / project managers see all in POC
    role = getattr(user, "role", None)
    role_val = getattr(role, "value", role) if role is not None else None
    if role_val in ("admin", "project_manager", "Admin", "Project Manager"):
        return True
    # If ACL project_id present and user has project membership, allow
    project_id = row.get("project_id") or (
        row.get("id") if entity.entity_type == "project" else None
    )
    if project_id is None:
        return True
    try:
        from app.models.team import TeamMember

        db = getattr(user, "_hydrate_db", None)
        if db is None:
            return True
        membership = (
            db.query(TeamMember)
            .filter(
                TeamMember.user_id == user.id,
                TeamMember.project_id == int(project_id),
            )
            .first()
        )
        return membership is not None or getattr(user, "id", None) == row.get(
            "project_manager_id"
        )
    except Exception:
        return True


def hydrate_entities(
    *,
    entity_type: str,
    ids: list[str],
    source: Optional[str] = None,
    context: Optional[dict] = None,
    user: Any = None,
) -> list[dict[str, Any]]:
    """Fetch authoritative rows for the given entity ids."""
    entity = get_entity_by_type(entity_type)
    if not entity:
        return []
    source = source or entity.source
    if not ids:
        return []

    start = time.time()
    session = _session_for_source(source, context)
    owns_session = session is not None and (
        not context or session is not context.get("db")
    )
    if session is None:
        return []

    try:
        if user is not None:
            try:
                user._hydrate_db = session  # type: ignore[attr-defined]
            except Exception:
                pass

        # Assets search_documents uses string ids already
        if entity.table == "search_documents":
            rows = session.execute(
                text(
                    "SELECT id, title, content, content_type, url, metadata_json "
                    "FROM search_documents WHERE id IN :ids"
                ).bindparams(),
                {},
            )
            # SQLAlchemy IN with expanding - use simpler loop for portability
            out: list[dict[str, Any]] = []
            for rid in ids:
                r = session.execute(
                    text(
                        "SELECT id, title, content, content_type, url, metadata_json "
                        "FROM search_documents WHERE id = :id"
                    ),
                    {"id": rid},
                ).mappings().first()
                if r:
                    d = dict(r)
                    if _authorize_row(entity, d, user):
                        out.append(d)
            _record_hydrate_metric(time.time() - start, len(out))
            return out

        cols = list(entity.hydrate_fields) or [entity.id_field]
        if entity.id_field not in cols:
            cols = [entity.id_field, *cols]
        # Whitelist columns to avoid injection
        safe_cols = [c for c in cols if c.replace("_", "").isalnum()]
        col_sql = ", ".join(safe_cols)
        table = entity.table
        if not table.replace("_", "").isalnum():
            return []

        out = []
        for rid in ids:
            try:
                int_id = int(rid)
            except (TypeError, ValueError):
                continue
            row = session.execute(
                text(f"SELECT {col_sql} FROM {table} WHERE {entity.id_field} = :id"),
                {"id": int_id},
            ).mappings().first()
            if not row:
                continue
            d = dict(row)
            if _authorize_row(entity, d, user):
                d["_entity_type"] = entity.entity_type
                d["_source"] = source
                out.append(d)
        _record_hydrate_metric(time.time() - start, len(out))
        return out
    except Exception as exc:
        logger.warning("Hydrate failed for %s: %s", entity_type, exc)
        return []
    finally:
        if owns_session and session is not None:
            session.close()


def _record_hydrate_metric(seconds: float, count: int) -> None:
    try:
        from app.search.metrics import record_hydrate

        record_hydrate(seconds * 1000, count)
    except Exception:
        pass


def enrich_hits_from_sql(
    hits: list[dict[str, Any]],
    *,
    context: Optional[dict] = None,
    user: Any = None,
) -> list[dict[str, Any]]:
    """Merge authoritative SQL fields into discovery hits (in-place copy)."""
    if not settings.SEARCH_HYDRATE_FROM_SQL or not hits:
        return hits

    # Group ids by (source, entity_type)
    groups: dict[tuple[str, str], list[str]] = {}
    for hit in hits:
        meta = hit.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        ctype = str(hit.get("content_type") or meta.get("entity_type") or "")
        source = str(
            meta.get("database_id")
            or meta.get("source_database")
            or hit.get("source_database")
            or ""
        )
        entity = get_entity_by_type(ctype)
        if not entity:
            continue
        source = source or entity.source
        rid = hit.get("entity_id") or _parse_entity_id(str(hit.get("id") or ""), ctype)
        if not rid:
            continue
        groups.setdefault((source, ctype), []).append(str(rid))

    hydrated_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (source, ctype), ids in groups.items():
        rows = hydrate_entities(
            entity_type=ctype,
            ids=list(dict.fromkeys(ids)),
            source=source,
            context=context,
            user=user,
        )
        for row in rows:
            key_id = str(row.get("id") or row.get("entity_id") or "")
            hydrated_map[(source, ctype, key_id)] = row

    enriched: list[dict[str, Any]] = []
    for hit in hits:
        h = dict(hit)
        meta = h.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        else:
            meta = dict(meta)
        ctype = str(h.get("content_type") or "")
        source = str(
            meta.get("database_id")
            or meta.get("source_database")
            or h.get("source_database")
            or ""
        )
        entity = get_entity_by_type(ctype)
        if entity:
            source = source or entity.source
        rid = str(h.get("entity_id") or _parse_entity_id(str(h.get("id") or ""), ctype) or "")
        row = hydrated_map.get((source, ctype, rid))
        if row:
            meta["hydrated"] = True
            meta["source_of_truth"] = "sql"
            # Prefer SQL title/description when present
            if row.get("name") and ctype == "project":
                h["title"] = row["name"]
            if row.get("title") and ctype in {"task", "drawing", "material"}:
                h["title"] = row["title"]
            if row.get("description"):
                meta["description"] = row["description"]
            if row.get("status") is not None:
                meta["status"] = (
                    row["status"].value if hasattr(row["status"], "value") else row["status"]
                )
            if row.get("location"):
                meta["location"] = row["location"]
            if row.get("progress") is not None:
                meta["progress"] = row["progress"]
            if row.get("drawing_no"):
                meta["drawing_no"] = row["drawing_no"]
            if row.get("file_url"):
                meta["file_url"] = row["file_url"]
            h["metadata"] = meta
        enriched.append(h)
    return enriched
