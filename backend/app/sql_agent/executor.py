"""Execute validated read-only SQL against a Space DB and map rows to search hits."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.space_databases import get_space_db_config, resolve_space_database_url

logger = logging.getLogger(__name__)


def _engine_for_source(source_id: str):
    from scripts.setup_assets_db import create_mssql_engine

    cfg = get_space_db_config(source_id)
    if cfg is not None:
        return create_mssql_engine(resolve_space_database_url(cfg))
    # Backward compat: Action only
    from app.search.space_indexer import _space_engine

    return _space_engine()


def _row_get_ci(data: dict[str, Any], *names: str) -> Any:
    """Case-insensitive column lookup."""
    lower_map = {str(k).lower(): k for k in data}
    for name in names:
        key = lower_map.get(name.lower())
        if key is not None and data.get(key) is not None:
            return data.get(key)
    return None


def _promote_join_keys(data: dict[str, Any], meta: dict[str, Any]) -> None:
    """Lift shared Space keys onto hit metadata for cross-DB linking."""
    project_id = _row_get_ci(data, "ProjectId", "ProjectID")
    if project_id is None:
        # DMS / Action: DimensionId when DimensionType is Project
        dim_type = _row_get_ci(data, "DimensionType")
        dim_id = _row_get_ci(data, "DimensionId")
        if (
            dim_type is not None
            and str(dim_type).strip().upper() == "PROJECT"
            and dim_id is not None
            and str(dim_id).strip().isdigit()
        ):
            project_id = dim_id
    if project_id is None:
        # Project master PK may be exposed as Id when SQL selects Id only.
        dbid = str(meta.get("database_id") or "")
        if dbid in {"space-project", "space"}:
            project_id = _row_get_ci(data, "Id")
    if project_id is not None and str(project_id).strip():
        pid = str(project_id).strip()
        if pid.isdigit():
            meta["space_project_id"] = pid
            # Space-only namespace — do not confuse with BuildTrack project_id.
            meta["project_id"] = pid

    user_id = _row_get_ci(data, "UserId", "UserID")
    if user_id is not None and str(user_id).strip():
        meta["user_id"] = str(user_id).strip()

    document_id = _row_get_ci(data, "DocumentId", "DocumentID")
    if document_id is not None and str(document_id).strip():
        meta["document_id"] = str(document_id).strip()

    attachment_id = _row_get_ci(data, "AttachmentId", "AttachmentID")
    if attachment_id is not None and str(attachment_id).strip():
        meta["attachment_id"] = str(attachment_id).strip()

    # Display name for UI when present (Project master / named entities).
    pname = _row_get_ci(data, "Name", "ProjectName", "NameofContract")
    pcode = _row_get_ci(data, "Code", "ProjectCode")
    if pname is not None and str(pname).strip():
        display = str(pname).strip()
        meta.setdefault("project", display)
        meta.setdefault("project_name", display)
    elif pcode is not None and str(pcode).strip():
        display = str(pcode).strip()
        meta.setdefault("project", display)
        meta.setdefault("project_name", display)


def execute_readonly_sql(
    sql: str,
    *,
    source_id: str = "space",
    source_label: str = "Space Action",
    content_type: str = "schema_sql",
    max_rows: Optional[int] = None,
) -> list[dict[str, Any]]:
    timeout = int(settings.SCHEMA_SQL_TIMEOUT_SECONDS or 15)
    engine = _engine_for_source(source_id)
    hits: list[dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            result = conn.execution_options(timeout=timeout).execute(text(sql))
            rows = result.mappings().fetchmany(
                int(max_rows or settings.SCHEMA_SQL_MAX_ROWS or 50)
            )
            keys = list(result.keys())
            for i, row in enumerate(rows):
                data = dict(row)
                title = _pick_title(data, keys) or f"Row {i + 1}"
                snippet_parts = [
                    f"{k}: {data[k]}"
                    for k in keys[:8]
                    if data.get(k) is not None and str(data.get(k)).strip()
                ]
                meta: dict[str, Any] = {
                    "database_id": source_id,
                    "database_label": source_label,
                    "retrieval": "schema_sql",
                    "sql": sql[:2000],
                    "row": {k: _jsonable(data.get(k)) for k in keys[:20]},
                }
                _promote_join_keys(data, meta)
                hits.append(
                    {
                        "id": f"schema-sql-{source_id}-{i}",
                        "title": str(title)[:200],
                        "snippet": " · ".join(snippet_parts)[:500],
                        "content_type": content_type,
                        "url": "",
                        "score": max(0.5, 1.0 - (i * 0.02)),
                        "metadata": meta,
                    }
                )
    except Exception as exc:
        logger.warning("Schema SQL execution failed (%s): %s", source_id, exc)
        raise
    finally:
        engine.dispose()
    return hits


def _pick_title(data: dict[str, Any], keys: list[str]) -> Optional[str]:
    preferred = (
        "FullName",
        "DisplayName",
        "FirstName",
        "LastName",
        "Name",
        "Code",
        "FileName",
        "OriginalFileName",
        "DocumentName",
        "Title",
        "Agenda",
        "EventNumber",
        "Location",
        "SubLocation",
        "Email",
        "UserName",
        "MeetingTitle",
        "Description",
        "SiteAddress",
        "AssessmentMonth",
        "NameofContract",
        "IncidentNumber",
    )
    lower_map = {k.lower(): k for k in keys}
    for p in preferred:
        if p.lower() in lower_map:
            val = data.get(lower_map[p.lower()])
            if val is not None and str(val).strip():
                return str(val).strip()
    for k in keys:
        val = data.get(k)
        if val is not None and str(val).strip() and not str(k).lower().endswith("id"):
            return str(val).strip()
    return None


def _jsonable(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    return str(val)
