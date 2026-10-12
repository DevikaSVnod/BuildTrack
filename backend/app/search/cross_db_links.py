"""
Cross-database relationship linking for Global Search.

When results from one DB share a business key with another DB (today: project name),
we:
  1) Tag existing hits so the UI/answer knows they are related
  2) Pull missing related records from the other DB and attach them

This is soft-key linking (not a SQL JOIN across Azure databases).
"""
from __future__ import annotations

import logging
import re
import time
from threading import Lock
from typing import Any, Callable, Optional

from sqlalchemy import text

from global_search_core.models import SearchHit

logger = logging.getLogger(__name__)

# The same project is looked up from several call sites during one search, and
# each lookup is a fresh connection + query against Azure SQL. Memoize briefly.
_LOOKUP_TTL = 60
_lookup_cache: dict[str, tuple[float, list[SearchHit]]] = {}
_lookup_lock = Lock()

def _cached_lookup(key: str, loader: Callable[[], list[SearchHit]]) -> list[SearchHit]:
    now = time.time()
    with _lookup_lock:
        entry = _lookup_cache.get(key)
        if entry is not None and now - entry[0] < _LOOKUP_TTL:
            return [dict(h) for h in entry[1]]
    hits = loader()
    with _lookup_lock:
        _lookup_cache[key] = (time.time(), hits)
        if len(_lookup_cache) > 200:
            for stale, _ in sorted(_lookup_cache.items(), key=lambda x: x[1][0])[:60]:
                _lookup_cache.pop(stale, None)
    return [dict(h) for h in hits]


def clear_cross_db_cache() -> None:
    with _lookup_lock:
        _lookup_cache.clear()

# Optional aliases when display names diverge slightly across DBs.
PROJECT_ALIASES: dict[str, str] = {
    "highway bridge": "Highway Bridge Expansion",
    "commercial tower": "Commercial Tower Phase 2",
    "metro station": "Metro Station Renovation",
    "industrial warehouse": "Industrial Warehouse Build",
    "residential complex": "Residential Complex A",
}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def canonical_project_name(raw: str) -> str:
    """Normalize / alias a project name to a stable join key display form."""
    key = _norm(raw)
    if not key:
        return ""
    alias = PROJECT_ALIASES.get(key)
    if alias:
        return alias
    # Match alias prefixes (e.g. "highway bridge expansion" → canonical)
    for short, full in PROJECT_ALIASES.items():
        if key == _norm(full) or key.startswith(short):
            return full
    return raw.strip()


def project_key_from_hit(hit: SearchHit) -> str:
    meta = hit.get("metadata") or {}
    ctype = str(hit.get("content_type") or "")
    candidates = [
        meta.get("project"),
        meta.get("project_name"),
        hit.get("title") if ctype == "project" else None,
    ]
    for c in candidates:
        if c and str(c).strip():
            return canonical_project_name(str(c))
    return ""


def space_project_id_from_hit(hit: SearchHit) -> str:
    """Numeric Space ProjectId from promoted metadata or nested row."""
    meta = hit.get("metadata") or {}
    for key in ("space_project_id", "project_id"):
        val = meta.get(key)
        if val is not None and str(val).strip():
            # Ignore non-numeric BuildTrack-style ids that aren't Space
            s = str(val).strip()
            if s.isdigit():
                return s
    row = meta.get("row")
    if isinstance(row, dict):
        for k, v in row.items():
            if str(k).lower() in ("projectid",) and v is not None and str(v).strip():
                s = str(v).strip()
                if s.isdigit():
                    return s
        # DMS / Action often store project as DimensionId + DimensionType=Project
        dim_type = None
        dim_id = None
        for k, v in row.items():
            lk = str(k).lower()
            if lk == "dimensiontype" and v is not None:
                dim_type = str(v).strip().upper()
            if lk == "dimensionid" and v is not None and str(v).strip().isdigit():
                dim_id = str(v).strip()
        if dim_type == "PROJECT" and dim_id:
            return dim_id
        # Project master sometimes exposes only Id when SQL omitted ProjectId alias.
        dbid = str(meta.get("database_id") or "")
        if dbid in {"space-project", "space"} or str(hit.get("content_type") or "") in {
            "space_project",
            "schema_sql",
        }:
            for k, v in row.items():
                if str(k).lower() == "id" and v is not None and str(v).strip().isdigit():
                    return str(v).strip()
    return ""


def _is_space_database_id(database_id: Optional[str]) -> bool:
    sid = (database_id or "").strip()
    return sid == "space" or sid.startswith("space-")


# Space ProjectId hop definitions: (source_id, table_key, sql_template, content_type, pk_col, title_cols)
_SPACE_PROJECT_HOPS: tuple[dict[str, Any], ...] = (
    {
        "source_id": "space-project",
        "table": "Project",
        "schema": "project",
        "content_type": "space_project",
        "pk": "ProjectId",
        "sql": (
            "SELECT TOP ({limit}) ProjectId, Code, Name, StatusId, SiteAddress, IsActive "
            "FROM project.[Project] WHERE ProjectId = :pid"
        ),
        "title_cols": ("Name", "Code"),
    },
    {
        "source_id": "space-hse",
        "table": "Occupational_Review",
        "schema": "hse",
        "content_type": "occupational_review",
        "pk": "OccupationalReviewId",
        "sql": (
            "SELECT TOP ({limit}) OccupationalReviewId, ProjectId, Number, ReviewDate, "
            "ReviewBy, IsSubmitted, IsActive "
            "FROM hse.[Occupational_Review] WHERE ProjectId = :pid AND IsActive = 1"
        ),
        "title_cols": ("Number",),
    },
    {
        "source_id": "space-hse",
        "table": "Environmental_Review",
        "schema": "hse",
        "content_type": "environmental_review",
        "pk": "EnvironmentalReviewId",
        "sql": (
            "SELECT TOP ({limit}) EnvironmentalReviewId, ProjectId, Number, ReviewDate, "
            "ReviewBy, IsSubmitted, IsActive "
            "FROM hse.[Environmental_Review] WHERE ProjectId = :pid AND IsActive = 1"
        ),
        "title_cols": ("Number",),
    },
    {
        "source_id": "space-incident",
        "table": "Incident_Information",
        "schema": "incident",
        "content_type": "incident",
        "pk": "IncidentId",
        "sql": (
            "SELECT TOP ({limit}) IncidentId, ProjectId, IncidentNumber, ReportDate, "
            "IncidentDateTime, Details, IsActive "
            "FROM incident.[Incident_Information] WHERE ProjectId = :pid AND IsActive = 1"
        ),
        "title_cols": ("IncidentNumber", "Details"),
    },
    {
        "source_id": "space-lms",
        "table": "Employment",
        "schema": "lms",
        "content_type": "employment",
        "pk": "EmploymentId",
        "sql": (
            "SELECT TOP ({limit}) EmploymentId, ProjectId, LabourId, ContractorId, "
            "SerialNumber, JoiningDate, EmploymentStatusId "
            "FROM lms.[Employment] WHERE ProjectId = :pid"
        ),
        "title_cols": ("SerialNumber", "EmploymentId"),
    },
    {
        "source_id": "space-cms",
        "table": "ProjectCM",
        "schema": "cms",
        "content_type": "contract",
        "pk": "ProjectCMID",
        "sql": (
            "SELECT TOP ({limit}) ProjectCMID, ProjectId, NameofContract, ContractNo, "
            "EmployerName, ContractorName, ExpectedCompletionDate "
            "FROM cms.[ProjectCM] WHERE ProjectId = :pid"
        ),
        "title_cols": ("NameofContract", "ContractNo"),
    },
    {
        "source_id": "space-dashboard",
        "table": "Dashboard_Project_Details",
        "schema": "dbo",
        "content_type": "dashboard_project",
        "pk": "Id",
        "sql": (
            "SELECT TOP ({limit}) Id, ProjectId, UserId, Address, City, ClientEmployer, "
            "ContractValue, Description, ActualStartDate, ActualEndDate "
            "FROM dbo.[Dashboard_Project_Details] WHERE ProjectId = :pid"
        ),
        "title_cols": ("ClientEmployer", "Address", "Description"),
    },
    # ── Deferred hops (DMS / Action dimension, UM, LMS attendance, CHKWP) ──
    {
        "source_id": "space-dms",
        "table": "Document",
        "schema": "dms",
        "content_type": "dms_document",
        "pk": "DocumentId",
        "sql": (
            "SELECT TOP ({limit}) d.DocumentId, d.DocumentNumber, d.Title, d.DocumentDate, "
            "d.IsActive, m.DimensionId AS ProjectId "
            "FROM dms.[Document] d "
            "INNER JOIN dms.[Document_MetaData] m ON m.DocumentId = d.DocumentId "
            "WHERE UPPER(LTRIM(RTRIM(m.DimensionType))) = 'PROJECT' "
            "AND m.DimensionId = :pid AND ISNULL(d.IsActive, 1) = 1 "
            "AND ISNULL(d.IsDeleted, 0) = 0"
        ),
        "title_cols": ("Title", "DocumentNumber"),
    },
    {
        "source_id": "space-dms",
        "table": "Document_File",
        "schema": "dms",
        "content_type": "dms_document_file",
        "pk": "DocumentFileId",
        "sql": (
            "SELECT TOP ({limit}) f.DocumentFileId, f.DocumentId, f.AttachmentId, "
            "f.FileVersion, d.Title, d.DocumentNumber, m.DimensionId AS ProjectId "
            "FROM dms.[Document_File] f "
            "INNER JOIN dms.[Document] d ON d.DocumentId = f.DocumentId "
            "INNER JOIN dms.[Document_MetaData] m ON m.DocumentId = d.DocumentId "
            "WHERE UPPER(LTRIM(RTRIM(m.DimensionType))) = 'PROJECT' "
            "AND m.DimensionId = :pid AND ISNULL(f.IsActive, 1) = 1"
        ),
        "title_cols": ("Title", "DocumentNumber", "FileVersion"),
    },
    {
        "source_id": "space",
        "table": "Events",
        "schema": "action",
        "content_type": "event",
        "pk": "EventId",
        "sql": (
            "SELECT TOP ({limit}) e.EventId, e.EventNumber, e.Title, e.Location, "
            "e.ScheduledStartDateTime, e.StatusId, e.IsActive, i.DimensionId AS ProjectId "
            "FROM action.[Events] e "
            "INNER JOIN action.[Event_Information] i ON i.EventId = e.EventId "
            "WHERE UPPER(LTRIM(RTRIM(i.DimensionType))) = 'PROJECT' "
            "AND i.DimensionId = :pid AND ISNULL(e.IsActive, 1) = 1"
        ),
        "title_cols": ("Title", "EventNumber"),
    },
    {
        "source_id": "space",
        "table": "Event_Agenda",
        "schema": "action",
        "content_type": "event_agenda",
        "pk": "EventAgendaId",
        "sql": (
            "SELECT TOP ({limit}) a.EventAgendaId, a.EventId, a.Agenda, "
            "e.EventNumber, e.Title, i.DimensionId AS ProjectId "
            "FROM action.[Event_Agenda] a "
            "INNER JOIN action.[Events] e ON e.EventId = a.EventId "
            "INNER JOIN action.[Event_Information] i ON i.EventId = e.EventId "
            "WHERE UPPER(LTRIM(RTRIM(i.DimensionType))) = 'PROJECT' "
            "AND i.DimensionId = :pid AND ISNULL(a.IsActive, 1) = 1"
        ),
        "title_cols": ("Agenda", "Title", "EventNumber"),
    },
    {
        "source_id": "space",
        "table": "Event_Task",
        "schema": "action",
        "content_type": "event_task",
        "pk": "EventTaskId",
        "sql": (
            "SELECT TOP ({limit}) t.EventTaskId, t.EventId, t.TaskNumber, t.Description, "
            "t.CompletionDate, e.EventNumber, e.Title, i.DimensionId AS ProjectId "
            "FROM action.[Event_Task] t "
            "INNER JOIN action.[Events] e ON e.EventId = t.EventId "
            "INNER JOIN action.[Event_Information] i ON i.EventId = e.EventId "
            "WHERE UPPER(LTRIM(RTRIM(i.DimensionType))) = 'PROJECT' "
            "AND i.DimensionId = :pid AND ISNULL(t.IsActive, 1) = 1"
        ),
        "title_cols": ("TaskNumber", "Description", "Title"),
    },
    {
        "source_id": "space-um",
        "table": "Users",
        "schema": "um",
        "content_type": "space_user",
        "pk": "UserId",
        "sql": (
            "SELECT TOP ({limit}) u.UserId, u.FirstName, u.LastName, u.Title, u.StatusId, "
            "u.IsActive, a.ProjectId, auth.Email, auth.Username, emp.EmployeeCode "
            "FROM um.[Users] u "
            "INNER JOIN um.[User_Assignment] a ON a.UserId = u.UserId "
            "LEFT JOIN um.[User_Auth] auth ON auth.UserId = u.UserId AND ISNULL(auth.IsActive, 1) = 1 "
            "LEFT JOIN um.[User_Employment] emp ON emp.UserId = u.UserId AND ISNULL(emp.IsActive, 1) = 1 "
            "WHERE a.ProjectId = :pid AND ISNULL(a.IsActive, 1) = 1 AND ISNULL(u.IsActive, 1) = 1"
        ),
        "title_cols": ("FirstName", "LastName", "Email", "EmployeeCode"),
    },
    {
        "source_id": "space-lms",
        "table": "Labour_Attendance",
        "schema": "lms",
        "content_type": "labour_attendance",
        "pk": "LabourAttendanceId",
        "sql": (
            "SELECT TOP ({limit}) LabourAttendanceId, ProjectId, LabourId, EmploymentId, "
            "ContractorId, AttendanceDate, WorkHours, OTHours, IsActive "
            "FROM lms.[Labour_Attendance] "
            "WHERE ProjectId = :pid AND ISNULL(IsActive, 1) = 1 "
            "ORDER BY AttendanceDate DESC"
        ),
        "title_cols": ("AttendanceDate", "LabourAttendanceId"),
    },
    {
        "source_id": "space-chkwp",
        "table": "Submission",
        "schema": "chkwp",
        "content_type": "checkpoint_submission",
        "pk": "SubmissionId",
        "sql": (
            "SELECT TOP ({limit}) SubmissionId, ProjectId, SubmissionNumber, LocationDetails, "
            "CaptureDateTime, StatusId, IsActive "
            "FROM chkwp.[Submission] "
            "WHERE ProjectId = :pid AND ProjectId <> 0 AND ISNULL(IsActive, 1) = 1"
        ),
        "title_cols": ("SubmissionNumber", "LocationDetails"),
    },
)


def _space_engine(source_id: str):
    from app.core.space_databases import get_space_db_config, resolve_space_database_url
    from scripts.setup_assets_db import create_mssql_engine

    cfg = get_space_db_config(source_id)
    if cfg is None:
        return None
    return create_mssql_engine(resolve_space_database_url(cfg))


def _hit_from_space_row(
    *,
    source_id: str,
    source_label: str,
    table: str,
    content_type: str,
    pk_col: str,
    title_cols: tuple[str, ...],
    row: dict[str, Any],
    project_id: str,
    score: float = 0.48,
) -> SearchHit:
    lower_map = {str(k).lower(): k for k in row}
    pk_val = row.get(lower_map.get(pk_col.lower(), pk_col))
    title = None
    for col in title_cols:
        key = lower_map.get(col.lower())
        if key and row.get(key) is not None and str(row.get(key)).strip():
            title = str(row.get(key)).strip()
            break
    if not title:
        title = f"{table} {pk_val}" if pk_val is not None else table

    snippet_parts = [
        f"{k}: {row[k]}"
        for k in list(row.keys())[:8]
        if row.get(k) is not None and str(row.get(k)).strip()
    ]
    return {
        "id": f"cross-db-{source_id}-{table}-{pk_val}",
        "title": str(title)[:200],
        "snippet": " · ".join(snippet_parts)[:500],
        "content_type": content_type,
        "url": "",
        "score": score,
        "metadata": {
            "database_id": source_id,
            "database_label": source_label,
            "retrieval": "cross_db_space",
            "linked_by_relationship": True,
            "space_project_id": str(project_id),
            "project_id": str(project_id),
            "table": table,
            "row": {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in list(row.items())[:20]},
        },
    }


def _fetch_space_hop_uncached(
    hop: dict[str, Any],
    project_id: str,
    *,
    limit: int,
    enabled: set[str],
) -> list[SearchHit]:
    source_id = hop["source_id"]
    if source_id not in enabled:
        return []
    from app.core.data_sources import get_source

    source = get_source(source_id)
    label = source.label if source else source_id
    engine = _space_engine(source_id)
    if engine is None:
        return []
    lim = max(1, min(int(limit), 8))
    sql = hop["sql"].format(limit=lim)
    hits: list[SearchHit] = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), {"pid": int(project_id)}).mappings().fetchall()
            for row in rows:
                data = dict(row)
                hits.append(
                    _hit_from_space_row(
                        source_id=source_id,
                        source_label=label,
                        table=hop["table"],
                        content_type=hop["content_type"],
                        pk_col=hop["pk"],
                        title_cols=tuple(hop["title_cols"]),
                        row=data,
                        project_id=project_id,
                    )
                )
    except Exception as exc:
        logger.warning(
            "Space cross-db hop failed %s.%s ProjectId=%s: %s",
            source_id,
            hop["table"],
            project_id,
            exc,
        )
    finally:
        engine.dispose()
    return hits


def _fetch_space_hop(
    hop: dict[str, Any],
    project_id: str,
    *,
    limit: int,
    enabled: set[str],
) -> list[SearchHit]:
    return _cached_lookup(
        f"space|{hop['source_id']}|{hop['table']}|{project_id}|{limit}",
        lambda: _fetch_space_hop_uncached(
            hop, project_id, limit=limit, enabled=enabled
        ),
    )


def _tag_space_relationship(
    hit: SearchHit,
    *,
    project_id: str,
    related_databases: list[str],
    related_from: Optional[list[str]] = None,
    project_name: str = "",
) -> SearchHit:
    item = dict(hit)
    meta = dict(item.get("metadata") or {})
    meta["relationship"] = "same_project"
    meta["related_via"] = "space_project_id"
    meta["related_key"] = str(project_id)
    meta["space_project_id"] = str(project_id)
    meta["related_databases"] = related_databases
    if related_from:
        meta["related_from"] = related_from
    if project_name:
        meta.setdefault("project", project_name)
        meta.setdefault("project_name", project_name)
    item["metadata"] = meta
    return item


def _resolve_project_display_name(project_id: str, enabled: set[str]) -> str:
    """Best-effort name from space-project master."""
    if "space-project" not in enabled:
        return ""
    hop = next(h for h in _SPACE_PROJECT_HOPS if h["table"] == "Project")
    rows = _fetch_space_hop(hop, project_id, limit=1, enabled=enabled)
    if not rows:
        return ""
    meta = rows[0].get("metadata") or {}
    row = meta.get("row") or {}
    for col in ("Name", "Code"):
        if row.get(col):
            return str(row[col]).strip()
    return str(rows[0].get("title") or "").strip()


def attach_space_project_id_hits(
    merged: list[SearchHit],
    *,
    enabled: set[str],
    max_related: int = 8,
    per_hop_limit: int = 3,
) -> list[SearchHit]:
    """
    Expand Space hits that share a numeric ProjectId across Space DBs.
    Does not touch BuildTrack/assets name-based linking.
    """
    space_enabled = {s for s in enabled if _is_space_database_id(s)}
    if len(space_enabled) < 2:
        return merged

    by_pid: dict[str, list[SearchHit]] = {}
    for hit in merged:
        meta = hit.get("metadata") or {}
        dbid = str(meta.get("database_id") or "")
        if not _is_space_database_id(dbid):
            continue
        pid = space_project_id_from_hit(hit)
        if not pid:
            continue
        by_pid.setdefault(pid, []).append(hit)

    if not by_pid:
        return merged

    # Budget scales with seed projects so list queries can still pull DMS/Action/HSE hops.
    max_related = max(int(max_related), min(72, len(by_pid) * 6))

    out = list(merged)
    seen = _existing_ids(out)
    related_added: list[SearchHit] = []

    for project_id, group in by_pid.items():
        dbs_present = sorted(
            {
                str((h.get("metadata") or {}).get("database_id") or "")
                for h in group
                if (h.get("metadata") or {}).get("database_id")
            }
        )
        related_dbs = sorted(set(dbs_present) | space_enabled)
        seed_ids = [str(h.get("id")) for h in group if h.get("id")]
        project_name = ""
        project_code = ""
        for h in group:
            meta = h.get("metadata") or {}
            if meta.get("project") or meta.get("project_name"):
                project_name = str(meta.get("project") or meta.get("project_name"))
            row = meta.get("row") if isinstance(meta.get("row"), dict) else {}
            if row.get("Code") and not project_code:
                project_code = str(row.get("Code")).strip()
            if project_name and project_code:
                break
        if not project_name:
            project_name = _resolve_project_display_name(project_id, space_enabled)
        if not project_code:
            project_code = _resolve_project_code(project_id, space_enabled)

        # Tag seeds
        id_to_tagged = {
            str(h.get("id")): _tag_space_relationship(
                h,
                project_id=project_id,
                related_databases=related_dbs,
                related_from=seed_ids,
                project_name=project_name,
            )
            for h in group
            if h.get("id")
        }
        out = [id_to_tagged.get(str(h.get("id")), h) for h in out]

        for hop in _SPACE_PROJECT_HOPS:
            if hop["source_id"] not in space_enabled:
                continue
            if len(related_added) >= max_related:
                break
            # Skip only when this exact content type already seeded for the ProjectId.
            if any(
                str(h.get("content_type") or "") == hop["content_type"]
                and str((h.get("metadata") or {}).get("database_id") or "")
                == hop["source_id"]
                for h in group
            ):
                continue
            for hit in _fetch_space_hop(
                hop, project_id, limit=per_hop_limit, enabled=space_enabled
            ):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                related_added.append(
                    _tag_space_relationship(
                        hit,
                        project_id=project_id,
                        related_databases=related_dbs,
                        related_from=seed_ids,
                        project_name=project_name,
                    )
                )
                seen.add(hid)
                if len(related_added) >= max_related:
                    break

        # BMS uses ProjectBDID / name-code, not Space ProjectId.
        if "space-bms" in space_enabled and len(related_added) < max_related:
            for hit in _fetch_bms_project_hits(
                project_name=project_name,
                project_code=project_code,
                limit=per_hop_limit,
                enabled=space_enabled,
            ):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                related_added.append(
                    _tag_space_relationship(
                        hit,
                        project_id=project_id,
                        related_databases=related_dbs,
                        related_from=seed_ids,
                        project_name=project_name,
                    )
                )
                seen.add(hid)
                if len(related_added) >= max_related:
                    break

    if related_added:
        logger.info(
            "Space cross-DB ProjectId attach: +%s related hit(s) for %s project(s)",
            len(related_added),
            len(by_pid),
        )
        out.extend(related_added)
        out.sort(key=lambda h: float(h.get("score") or 0), reverse=True)

    out = attach_space_attachment_id_hits(
        out, enabled=space_enabled, max_related=min(12, max_related)
    )
    out = attach_space_user_id_hits(
        out, enabled=space_enabled, max_related=min(12, max_related)
    )
    return out


def _resolve_project_code(project_id: str, enabled: set[str]) -> str:
    if "space-project" not in enabled:
        return ""
    hop = next(h for h in _SPACE_PROJECT_HOPS if h["table"] == "Project")
    rows = _fetch_space_hop(hop, project_id, limit=1, enabled=enabled)
    if not rows:
        return ""
    row = ((rows[0].get("metadata") or {}).get("row") or {})
    code = row.get("Code")
    return str(code).strip() if code else ""


def _fetch_bms_project_hits(
    *,
    project_name: str,
    project_code: str,
    limit: int,
    enabled: set[str],
) -> list[SearchHit]:
    if "space-bms" not in enabled:
        return []
    if not project_name and not project_code:
        return []

    def _load() -> list[SearchHit]:
        from app.core.data_sources import get_source

        source = get_source("space-bms")
        label = source.label if source else "Space BMS"
        engine = _space_engine("space-bms")
        if engine is None:
            return []
        lim = max(1, min(int(limit), 5))
        sql = (
            "SELECT TOP ({limit}) ProjectBDID, ProjectName, ProjectTempCode, "
            "ProjectSAPCode, ProjectStage, LocationDetails, ContractValue, IsActive "
            "FROM bms.[ProjectBD] WHERE ISNULL(IsActive, 1) = 1 AND ("
            "(:code <> '' AND (ProjectSAPCode = :code OR ProjectTempCode = :code)) "
            "OR (:name <> '' AND ProjectName = :name)"
            ")"
        ).format(limit=lim)
        hits: list[SearchHit] = []
        try:
            with engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(sql),
                        {"code": project_code or "", "name": project_name or ""},
                    )
                    .mappings()
                    .fetchall()
                )
                for row in rows:
                    data = dict(row)
                    hits.append(
                        _hit_from_space_row(
                            source_id="space-bms",
                            source_label=label,
                            table="ProjectBD",
                            content_type="bms_project",
                            pk_col="ProjectBDID",
                            title_cols=(
                                "ProjectName",
                                "ProjectSAPCode",
                                "ProjectTempCode",
                            ),
                            row=data,
                            project_id=str(data.get("ProjectBDID") or ""),
                            score=0.46,
                        )
                    )
        except Exception as exc:
            logger.warning("Space BMS name/code hop failed: %s", exc)
        finally:
            engine.dispose()
        return hits

    return _cached_lookup(
        f"space|bms|ProjectBD|{project_code}|{project_name}|{limit}",
        _load,
    )


def space_document_id_from_hit(hit: SearchHit) -> str:
    meta = hit.get("metadata") or {}
    for key in ("document_id", "DocumentId"):
        val = meta.get(key)
        if val is not None and str(val).strip().isdigit():
            return str(val).strip()
    row = meta.get("row")
    if isinstance(row, dict):
        for k, v in row.items():
            if str(k).lower() == "documentid" and v is not None and str(v).strip().isdigit():
                return str(v).strip()
    return ""


def space_user_id_from_hit(hit: SearchHit) -> str:
    meta = hit.get("metadata") or {}
    for key in ("user_id", "UserId"):
        val = meta.get(key)
        if val is not None and str(val).strip().isdigit():
            return str(val).strip()
    row = meta.get("row")
    if isinstance(row, dict):
        for k, v in row.items():
            if str(k).lower() == "userid" and v is not None and str(v).strip().isdigit():
                return str(v).strip()
    return ""


def space_attachment_id_from_hit(hit: SearchHit) -> str:
    meta = hit.get("metadata") or {}
    for key in ("attachment_id", "AttachmentId"):
        val = meta.get(key)
        if val is not None and str(val).strip().isdigit():
            return str(val).strip()
    row = meta.get("row")
    if isinstance(row, dict):
        for k, v in row.items():
            if str(k).lower() == "attachmentid" and v is not None and str(v).strip().isdigit():
                return str(v).strip()
    return ""


def attach_space_attachment_id_hits(
    merged: list[SearchHit],
    *,
    enabled: set[str],
    max_related: int = 12,
) -> list[SearchHit]:
    """Follow AttachmentId from DMS document files into Space Attachment storage."""
    if "space-attachment" not in enabled:
        return merged
    aids: list[str] = []
    seen_aids: set[str] = set()
    for hit in merged:
        aid = space_attachment_id_from_hit(hit)
        if not aid or aid in seen_aids:
            continue
        seen_aids.add(aid)
        aids.append(aid)
        if len(aids) >= 20:
            break
    if not aids:
        return merged

    from app.core.data_sources import get_source

    source = get_source("space-attachment")
    label = source.label if source else "Space Attachment"
    engine = _space_engine("space-attachment")
    if engine is None:
        return merged

    out = list(merged)
    seen = _existing_ids(out)
    added = 0
    try:
        with engine.connect() as conn:
            params = {f"a{i}": int(a) for i, a in enumerate(aids)}
            placeholders = ", ".join(f":a{i}" for i in range(len(aids)))
            sql = (
                "SELECT TOP (20) AttachmentId, FileName, FileDescription, BlobUrl, "
                "MimeType, FileSize, IsActive "
                f"FROM storage.[Attachment] WHERE AttachmentId IN ({placeholders}) "
                "AND ISNULL(IsActive, 1) = 1"
            )
            rows = conn.execute(text(sql), params).mappings().fetchall()
            for row in rows:
                data = dict(row)
                hit = _hit_from_space_row(
                    source_id="space-attachment",
                    source_label=label,
                    table="Attachment",
                    content_type="space_attachment",
                    pk_col="AttachmentId",
                    title_cols=("FileName", "FileDescription"),
                    row=data,
                    project_id=str(data.get("AttachmentId") or ""),
                    score=0.44,
                )
                meta = dict(hit.get("metadata") or {})
                meta["relationship"] = "same_attachment"
                meta["related_via"] = "space_attachment_id"
                meta["related_key"] = str(data.get("AttachmentId") or "")
                meta["attachment_id"] = str(data.get("AttachmentId") or "")
                hit["metadata"] = meta
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                out.append(hit)
                seen.add(hid)
                added += 1
                if added >= max_related:
                    break
    except Exception as exc:
        logger.warning("Space AttachmentId hop failed: %s", exc)
    finally:
        engine.dispose()

    if added:
        logger.info("Space AttachmentId attach: +%s hit(s)", added)
        out.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
    return out


def attach_space_user_id_hits(
    merged: list[SearchHit],
    *,
    enabled: set[str],
    max_related: int = 12,
) -> list[SearchHit]:
    """Follow UserId onto UM user profiles (UserId graph)."""
    if "space-um" not in enabled:
        return merged
    uids: list[str] = []
    seen_uids: set[str] = set()
    for hit in merged:
        if str(hit.get("content_type") or "") == "space_user":
            continue
        uid = space_user_id_from_hit(hit)
        if not uid or uid in seen_uids:
            continue
        seen_uids.add(uid)
        uids.append(uid)
        if len(uids) >= 20:
            break
    if not uids:
        return merged

    from app.core.data_sources import get_source

    source = get_source("space-um")
    label = source.label if source else "Space UM"
    engine = _space_engine("space-um")
    if engine is None:
        return merged

    out = list(merged)
    seen = _existing_ids(out)
    added = 0
    try:
        with engine.connect() as conn:
            params = {f"u{i}": int(u) for i, u in enumerate(uids)}
            placeholders = ", ".join(f":u{i}" for i in range(len(uids)))
            sql = (
                "SELECT TOP (20) u.UserId, u.FirstName, u.LastName, u.Title, u.StatusId, "
                "u.IsActive, auth.Email, auth.Username, emp.EmployeeCode "
                "FROM um.[Users] u "
                "LEFT JOIN um.[User_Auth] auth ON auth.UserId = u.UserId "
                "AND ISNULL(auth.IsActive, 1) = 1 "
                "LEFT JOIN um.[User_Employment] emp ON emp.UserId = u.UserId "
                "AND ISNULL(emp.IsActive, 1) = 1 "
                f"WHERE u.UserId IN ({placeholders}) AND ISNULL(u.IsActive, 1) = 1"
            )
            rows = conn.execute(text(sql), params).mappings().fetchall()
            for row in rows:
                data = dict(row)
                hit = _hit_from_space_row(
                    source_id="space-um",
                    source_label=label,
                    table="Users",
                    content_type="space_user",
                    pk_col="UserId",
                    title_cols=("FirstName", "LastName", "Email", "EmployeeCode"),
                    row=data,
                    project_id="",
                    score=0.45,
                )
                meta = dict(hit.get("metadata") or {})
                meta["relationship"] = "same_user"
                meta["related_via"] = "space_user_id"
                meta["related_key"] = str(data.get("UserId") or "")
                meta["user_id"] = str(data.get("UserId") or "")
                meta.pop("space_project_id", None)
                meta.pop("project_id", None)
                hit["metadata"] = meta
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                out.append(hit)
                seen.add(hid)
                added += 1
                if added >= max_related:
                    break
    except Exception as exc:
        logger.warning("Space UserId hop failed: %s", exc)
    finally:
        engine.dispose()

    if added:
        logger.info("Space UserId attach: +%s hit(s)", added)
        out.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
    return out


def _existing_ids(hits: list[SearchHit]) -> set[str]:
    return {str(h.get("id") or "") for h in hits if h.get("id")}


def _tag_relationship(
    hit: SearchHit,
    *,
    project: str,
    related_databases: list[str],
    related_from: Optional[list[str]] = None,
    via: str = "project_name",
) -> SearchHit:
    item = dict(hit)
    meta = dict(item.get("metadata") or {})
    meta["relationship"] = "same_project"
    meta["related_via"] = via
    meta["related_key"] = project
    meta["related_databases"] = related_databases
    if related_from:
        meta["related_from"] = related_from
    # Keep project fields consistent for UI filters.
    meta.setdefault("project", project)
    meta.setdefault("project_name", project)
    item["metadata"] = meta
    return item


def _fetch_assets_for_project(project: str, *, limit: int = 4) -> list[SearchHit]:
    return _cached_lookup(
        f"assets|{_norm(project)}|{limit}",
        lambda: _fetch_assets_for_project_uncached(project, limit=limit),
    )


def _fetch_assets_for_project_uncached(project: str, *, limit: int = 4) -> list[SearchHit]:
    from app.core.data_sources import get_source, session_for

    source = get_source("assets")
    if source is None:
        return []

    session = session_for("assets")
    hits: list[SearchHit] = []
    try:
        lim = max(1, min(int(limit), 20))
        equipment = session.execute(
            text(
                f"""
                SELECT TOP ({lim}) id, asset_tag, name, category, project_name, status,
                       vendor_name, location, notes
                FROM equipment
                WHERE LOWER(LTRIM(RTRIM(project_name))) = LOWER(LTRIM(RTRIM(:project)))
                ORDER BY asset_tag
                """
            ),
            {"project": project},
        ).fetchall()
        for row in equipment:
            r = row._mapping
            hits.append(
                {
                    "id": f"assets::equipment-{r['id']}",
                    "title": f"{r['asset_tag']} - {r['name']}",
                    "snippet": (r.get("notes") or f"{r['category']} · {r['status']}")[:220],
                    "content_type": "equipment",
                    "url": "/assets?tab=equipment",
                    "score": 0.55,
                    "metadata": {
                        "database_id": "assets",
                        "database_label": source.label,
                        "asset_tag": r["asset_tag"],
                        "category": r["category"],
                        "status": r["status"],
                        "project": r["project_name"],
                        "project_name": r["project_name"],
                        "vendor": r.get("vendor_name"),
                        "location": r.get("location"),
                        "linked_by_relationship": True,
                    },
                }
            )

        mat_lim = max(1, min(max(2, limit // 2), 20))
        materials = session.execute(
            text(
                f"""
                SELECT TOP ({mat_lim}) id, delivery_ref, material_name, quantity, unit,
                       project_name, vendor_name, status, notes
                FROM material_deliveries
                WHERE LOWER(LTRIM(RTRIM(project_name))) = LOWER(LTRIM(RTRIM(:project)))
                ORDER BY delivery_ref
                """
            ),
            {"project": project},
        ).fetchall()
        for row in materials:
            r = row._mapping
            hits.append(
                {
                    "id": f"assets::material-{r['id']}",
                    "title": f"{r['delivery_ref']} - {r['material_name']}",
                    "snippet": (
                        r.get("notes")
                        or f"{r['quantity']} {r['unit']} · {r['status']}"
                    )[:220],
                    "content_type": "material",
                    "url": "/assets?tab=materials",
                    "score": 0.5,
                    "metadata": {
                        "database_id": "assets",
                        "database_label": source.label,
                        "delivery_ref": r["delivery_ref"],
                        "quantity": r["quantity"],
                        "unit": r["unit"],
                        "status": r["status"],
                        "project": r["project_name"],
                        "project_name": r["project_name"],
                        "vendor": r.get("vendor_name"),
                        "linked_by_relationship": True,
                    },
                }
            )
    except Exception as exc:
        logger.warning("cross-db assets lookup failed for %s: %s", project, exc)
    finally:
        session.close()
    return hits


_PROJECT_ROSTER_KEY = "__buildtrack_project_roster__"


def _buildtrack_project_roster() -> list[Any]:
    """All BuildTrack projects, fetched once and matched in memory.

    One search can ask about a dozen project names; the table is small enough
    that a single fetch beats a query per name against Azure SQL.
    """
    now = time.time()
    with _lookup_lock:
        entry = _lookup_cache.get(_PROJECT_ROSTER_KEY)
        if entry is not None and now - entry[0] < _LOOKUP_TTL:
            return entry[1]

    from app.core.data_sources import session_for
    from app.models.project import Project

    rows: list[Any] = []
    try:
        session = session_for("buildtrack")
        try:
            rows = session.query(
                Project.id,
                Project.name,
                Project.description,
                Project.status,
                Project.progress,
                Project.location,
            ).all()
        finally:
            session.close()
    except Exception as exc:
        logger.warning("cross-db project roster load failed: %s", exc)
        return []

    with _lookup_lock:
        _lookup_cache[_PROJECT_ROSTER_KEY] = (time.time(), rows)
    return rows


def _match_project_row(project: str) -> Optional[Any]:
    target = _norm(project)
    if not target:
        return None
    roster = _buildtrack_project_roster()
    for row in roster:
        if _norm(row.name) == target:
            return row
    # Fallback: partial match on canonical short names
    for row in roster:
        if target in _norm(row.name):
            return row
    return None


def _fetch_buildtrack_project(project: str) -> list[SearchHit]:
    from app.core.data_sources import get_source

    source = get_source("buildtrack")
    if source is None:
        return []

    row = _match_project_row(project)
    if row is None:
        return []
    status = row.status.value if hasattr(row.status, "value") else str(row.status or "")
    return [
        {
            "id": f"buildtrack::project-{row.id}",
            "title": row.name,
            "snippet": (row.description or f"{status} · {row.progress or 0}% complete")[:220],
            "content_type": "project",
            "url": f"/projects/{row.id}",
            "score": 0.58,
            "metadata": {
                "database_id": "buildtrack",
                "database_label": source.label,
                "project_id": row.id,
                "project_name": row.name,
                "project": row.name,
                "status": status,
                "progress": row.progress,
                "location": row.location,
                "linked_by_relationship": True,
            },
        }
    ]


def _fetch_buildtrack_team_for_project(project: str, *, limit: int = 12) -> list[SearchHit]:
    """Workforce assigned to a project in BuildTrack (cross-DB hop from assets)."""
    return _cached_lookup(
        f"team|{_norm(project)}|{limit}",
        lambda: _fetch_buildtrack_team_for_project_uncached(project, limit=limit),
    )


def _fetch_buildtrack_team_for_project_uncached(
    project: str, *, limit: int = 12
) -> list[SearchHit]:
    from sqlalchemy.orm import joinedload

    from app.core.data_sources import get_source, session_for
    from app.models.team import TeamMember

    source = get_source("buildtrack")
    if source is None:
        return []

    proj = _match_project_row(project)
    if proj is None:
        return []

    session = session_for("buildtrack")
    hits: list[SearchHit] = []
    try:
        members = (
            session.query(TeamMember)
            .options(joinedload(TeamMember.user), joinedload(TeamMember.project))
            .filter(TeamMember.project_id == proj.id)
            .limit(limit)
            .all()
        )
        seen_users: set[int] = set()
        for m in members:
            user = m.user
            if not user or user.id in seen_users:
                continue
            seen_users.add(user.id)
            role = m.role or (user.role.value if getattr(user, "role", None) else "")
            hits.append(
                {
                    "id": f"buildtrack::workforce-{user.id}-p{proj.id}",
                    "title": user.full_name,
                    "snippet": f"{role} · {proj.name}",
                    "content_type": "team",
                    "url": f"/team?userId={user.id}",
                    "score": 0.72,
                    "metadata": {
                        "database_id": "buildtrack",
                        "database_label": source.label,
                        "role": role,
                        "email": user.email,
                        "user_id": user.id,
                        "project": proj.name,
                        "project_name": proj.name,
                        "project_id": proj.id,
                        "projects": [proj.name],
                        "linked_by_relationship": True,
                    },
                }
            )
    except Exception as exc:
        logger.warning("cross-db team lookup failed for %s: %s", project, exc)
    finally:
        session.close()
    return hits


def _query_wants_workforce(query: Optional[str]) -> bool:
    if not query:
        return False
    try:
        from app.search.query_intel import is_asset_to_people_hop_query

        if is_asset_to_people_hop_query(query):
            return True
    except Exception:
        pass
    q = _norm(query)
    return bool(
        re.search(
            r"\b(who\s+is\s+working|who\s+are\s+working|who\s+works|workforce|"
            r"personnel|team\s+members?|staff)\b",
            q,
        )
    )


def _team_matches_project(hit: SearchHit, project: str) -> bool:
    if not project:
        return False
    meta = hit.get("metadata") or {}
    target = _norm(project)
    for key in ("project", "project_name", "related_key"):
        if _norm(str(meta.get(key) or "")) == target:
            return True
    projects = meta.get("projects") or []
    if isinstance(projects, list) and any(_norm(str(p)) == target for p in projects):
        return True
    snippet = _norm(str(hit.get("snippet") or ""))
    return target in snippet


def _equipment_matches_query(hit: SearchHit, query: Optional[str]) -> bool:
    if str(hit.get("content_type") or "") not in {"equipment", "material"}:
        return False
    if not query:
        return True
    try:
        from app.search.result_filter import extract_asset_kind, _matches_asset_kind

        kind = extract_asset_kind(query)
        if kind and _matches_asset_kind(hit, kind):
            return True
    except Exception:
        pass
    q = _norm(query)
    # Phrase after colon: "…asset is used: 45-ton Hydraulic Excavator"
    if ":" in query:
        phrase = _norm(query.split(":")[-1])
        if phrase and phrase in _norm(
            f"{hit.get('title') or ''} {(hit.get('metadata') or {}).get('category') or ''}"
        ):
            return True
    hay = _norm(
        f"{hit.get('title') or ''} {(hit.get('metadata') or {}).get('category') or ''} "
        f"{(hit.get('metadata') or {}).get('asset_tag') or ''}"
    )
    for token in ("excavator", "crane", "generator", "scaffold", "boom", "pump"):
        if token in q and token in hay:
            return True
    return "asset" in q  # generic asset mention — keep any equipment hit


def _asset_projects_from_hits(merged: list[SearchHit], query: Optional[str]) -> list[str]:
    """Project keys taken only from equipment/material hits (not from team noise)."""
    equipment = [
        h
        for h in merged
        if str(h.get("content_type") or "") in {"equipment", "material"}
    ]
    matched = [h for h in equipment if _equipment_matches_query(h, query)]
    if not matched:
        matched = equipment
    keys: list[str] = []
    for h in matched:
        key = project_key_from_hit(h)
        if key and key not in keys:
            keys.append(key)
    return keys


def _resolve_asset_from_sql(query: str) -> tuple[list[SearchHit], list[str]]:
    """If search missed the asset, look it up in buildtrack_assets by kind/name."""
    from app.core.data_sources import get_source, session_for

    source = get_source("assets")
    if source is None:
        return [], []

    kind = ""
    try:
        from app.search.result_filter import extract_asset_kind

        kind = extract_asset_kind(query) or ""
    except Exception:
        pass
    phrase = ""
    if ":" in query:
        phrase = query.split(":")[-1].strip()

    session = session_for("assets")
    hits: list[SearchHit] = []
    projects: list[str] = []
    try:
        rows = session.execute(
            text(
                """
                SELECT id, asset_tag, name, category, project_name, status,
                       vendor_name, location, notes
                FROM equipment
                """
            )
        ).fetchall()
        for row in rows:
            r = row._mapping
            hay = _norm(f"{r['asset_tag']} {r['name']} {r['category']}")
            ok = False
            if phrase and _norm(phrase) in hay:
                ok = True
            elif kind and kind in hay:
                ok = True
            if not ok:
                continue
            project = canonical_project_name(str(r["project_name"] or ""))
            hits.append(
                {
                    "id": f"assets::equipment-{r['id']}",
                    "title": f"{r['asset_tag']} - {r['name']}",
                    "snippet": (r.get("notes") or f"{r['category']} · {r['status']}")[:220],
                    "content_type": "equipment",
                    "url": "/assets?tab=equipment",
                    "score": 0.95,
                    "metadata": {
                        "database_id": "assets",
                        "database_label": source.label,
                        "asset_tag": r["asset_tag"],
                        "category": r["category"],
                        "status": r["status"],
                        "project": r["project_name"],
                        "project_name": r["project_name"],
                        "vendor": r.get("vendor_name"),
                        "location": r.get("location"),
                        "linked_by_relationship": True,
                    },
                }
            )
            if project and project not in projects:
                projects.append(project)
    except Exception as exc:
        logger.warning("SQL asset resolve failed: %s", exc)
    finally:
        session.close()
    return hits, projects


def attach_related_hits(
    merged: list[SearchHit],
    *,
    query: Optional[str] = None,
    max_related: int = 6,
) -> list[SearchHit]:
    """
    Tag same-project hits across DBs and attach missing related records.

    For asset→people hop queries, ONLY expand from the asset's project
    (ignore unrelated workforce hits Azure Search may have returned).
    """
    if not merged:
        return merged

    from app.core.data_sources import get_enabled_sources

    enabled = {s.id for s in get_enabled_sources()}
    if len(enabled) < 2:
        return merged

    is_hop = False
    try:
        from app.search.query_intel import is_asset_to_people_hop_query

        is_hop = bool(query and is_asset_to_people_hop_query(query))
    except Exception:
        is_hop = False

    # ── Dedicated hop path: asset → project → people (strict) ─────────────
    if is_hop:
        asset_projects = _asset_projects_from_hits(merged, query)
        sql_assets: list[SearchHit] = []
        if not asset_projects and query:
            sql_assets, asset_projects = _resolve_asset_from_sql(query)

        if not asset_projects:
            return merged

        seed_equip: list[SearchHit] = []
        for h in list(merged) + sql_assets:
            if str(h.get("content_type") or "") not in {"equipment", "material"}:
                continue
            key = project_key_from_hit(h)
            if key in asset_projects or _equipment_matches_query(h, query):
                if key and key not in asset_projects:
                    asset_projects.append(key)
                seed_equip.append(h)

        # Dedupe seed equipment
        deduped: list[SearchHit] = []
        seen_seed: set[str] = set()
        for h in seed_equip:
            hid = str(h.get("id") or "")
            if hid in seen_seed:
                continue
            if hid:
                seen_seed.add(hid)
            deduped.append(h)
        seed_equip = deduped

        out: list[SearchHit] = []
        seen: set[str] = set()
        for h in seed_equip:
            project = project_key_from_hit(h) or (asset_projects[0] if asset_projects else "")
            tagged = _tag_relationship(
                h,
                project=project,
                related_databases=["assets", "buildtrack"],
                related_from=[str(h.get("id"))],
            )
            hid = str(tagged.get("id") or "")
            if hid and hid not in seen:
                seen.add(hid)
                out.append(tagged)

        for project in asset_projects:
            for hit in _fetch_buildtrack_project(project):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                out.append(
                    _tag_relationship(
                        hit,
                        project=project,
                        related_databases=["assets", "buildtrack"],
                        related_from=[str(x.get("id")) for x in seed_equip if x.get("id")],
                    )
                )
                seen.add(hid)
            for hit in _fetch_buildtrack_team_for_project(project):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                out.append(
                    _tag_relationship(
                        hit,
                        project=project,
                        related_databases=["assets", "buildtrack"],
                        related_from=[str(x.get("id")) for x in seed_equip if x.get("id")],
                        via="project_name->workforce",
                    )
                )
                seen.add(hid)

        out.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
        logger.info(
            "Cross-DB hop (asset→people): projects=%s hits=%s",
            asset_projects,
            [(h.get("content_type"), h.get("title")) for h in out],
        )
        return out

    # ── Generic same-project linking ──────────────────────────────────────
    by_project: dict[str, list[SearchHit]] = {}
    for hit in merged:
        # Do not let team docs seed unrelated project expansions by themselves
        # when they only carry a projects[] list with many names.
        if str(hit.get("content_type") or "") == "team":
            meta = hit.get("metadata") or {}
            single = meta.get("project") or meta.get("project_name")
            if not single:
                continue
        key = project_key_from_hit(hit)
        if not key:
            continue
        by_project.setdefault(key, []).append(hit)

    if not by_project:
        # No name-based BuildTrack/assets keys — still try Space ProjectId expansion.
        return attach_space_project_id_hits(
            merged, enabled=enabled, max_related=max_related
        )

    wants_people = _query_wants_workforce(query)
    if wants_people:
        max_related = max(max_related, 14)

    out = list(merged)
    seen = _existing_ids(out)
    related_added: list[SearchHit] = []

    for project, group in by_project.items():
        dbs_present = sorted(
            {
                str((h.get("metadata") or {}).get("database_id") or "")
                for h in group
                if (h.get("metadata") or {}).get("database_id")
            }
        )
        related_dbs = sorted(set(dbs_present) | (enabled & {"buildtrack", "assets"}))
        seed_ids = [str(h.get("id")) for h in group if h.get("id")]

        tagged_group = [
            _tag_relationship(
                h,
                project=project,
                related_databases=related_dbs,
                related_from=seed_ids,
            )
            for h in group
        ]
        id_to_tagged = {str(h.get("id")): h for h in tagged_group}
        out = [id_to_tagged.get(str(h.get("id")), h) for h in out]

        if "assets" in enabled and "assets" not in dbs_present and len(related_added) < max_related:
            for hit in _fetch_assets_for_project(project):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                related_added.append(
                    _tag_relationship(
                        hit,
                        project=project,
                        related_databases=related_dbs,
                        related_from=seed_ids,
                    )
                )
                seen.add(hid)
                if len(related_added) >= max_related:
                    break

        if (
            "buildtrack" in enabled
            and "buildtrack" not in dbs_present
            and len(related_added) < max_related
        ):
            for hit in _fetch_buildtrack_project(project):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                related_added.append(
                    _tag_relationship(
                        hit,
                        project=project,
                        related_databases=related_dbs,
                        related_from=seed_ids,
                    )
                )
                seen.add(hid)
                if len(related_added) >= max_related:
                    break

        if (
            "buildtrack" in enabled
            and "assets" in dbs_present
            and not any(
                str(h.get("content_type")) == "project"
                and _norm(str(h.get("title") or "")) == _norm(project)
                for h in out
            )
            and len(related_added) < max_related
        ):
            for hit in _fetch_buildtrack_project(project):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                related_added.append(
                    _tag_relationship(
                        hit,
                        project=project,
                        related_databases=["buildtrack", "assets"],
                        related_from=seed_ids,
                    )
                )
                seen.add(hid)
                break

        if wants_people and "buildtrack" in enabled and len(related_added) < max_related:
            # Only expand workforce from asset/project seeds, not from random team hits
            seeded_by_asset = any(
                str(h.get("content_type") or "") in {"equipment", "material", "project"}
                for h in group
            )
            if not seeded_by_asset:
                continue
            for hit in _fetch_buildtrack_team_for_project(project):
                hid = str(hit.get("id") or "")
                if not hid or hid in seen:
                    continue
                related_added.append(
                    _tag_relationship(
                        hit,
                        project=project,
                        related_databases=["buildtrack", "assets"],
                        related_from=seed_ids,
                        via="project_name->workforce",
                    )
                )
                seen.add(hid)
                if len(related_added) >= max_related:
                    break

    if related_added:
        logger.info(
            "Cross-DB relationship attach: +%s related hit(s) via project_name%s",
            len(related_added),
            " (+workforce hop)" if wants_people else "",
        )
        out.extend(related_added)
        out.sort(key=lambda h: float(h.get("score") or 0), reverse=True)

    # Space ProjectId expansion (separate key namespace from BuildTrack names).
    out = attach_space_project_id_hits(
        out, enabled=enabled, max_related=max_related
    )
    return out