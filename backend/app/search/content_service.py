"""Load all read-only page data from Azure AI Search (SQL indexer output)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from app.search import index_reader
from app.search.content_mappers import (
    kpi_metadata,
    map_attendance,
    map_budget_reports,
    map_documents,
    map_drawings,
    map_handover,
    map_milestones,
    map_projects,
    map_safety_incidents,
    map_tasks,
    map_team,
    map_timeline,
)


_load_pool = ThreadPoolExecutor(max_workers=6)


def _load(*types: str) -> dict[str, list[dict[str, Any]]]:
    if not types:
        return {}
    if len(types) == 1:
        t = types[0]
        return {t: index_reader.list_indexed(t)}
    futures = {_load_pool.submit(index_reader.list_indexed, t): t for t in types}
    return {futures[fut]: fut.result() for fut in futures}


def projects(status_filter: Optional[str] = None) -> list[dict[str, Any]]:
    from app.core.config import settings

    # Production path: SQL is source of truth for project lists.
    if settings.SEARCH_HYDRATE_FROM_SQL:
        return _projects_from_sql(status_filter=status_filter)

    bundle = _load("project", "task", "team")
    rows = map_projects(bundle["project"], bundle["task"], bundle["team"])
    if status_filter and status_filter != "all":
        rows = [r for r in rows if r.get("status") == status_filter]
    return rows


def _projects_from_sql(status_filter: Optional[str] = None) -> list[dict[str, Any]]:
    """Authoritative project list from Azure SQL / primary DB."""
    from sqlalchemy.orm import joinedload

    from app.core.database import SessionLocal
    from app.models.project import Project

    db = SessionLocal()
    try:
        q = db.query(Project).options(
            joinedload(Project.project_manager),
            joinedload(Project.tasks),
            joinedload(Project.team_members),
        )
        rows = q.all()
        out: list[dict[str, Any]] = []
        for p in rows:
            status = p.status.value if p.status else ""
            if status_filter and status_filter != "all" and status != status_filter:
                continue
            pm = p.project_manager
            out.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "status": status,
                    "start_date": p.start_date,
                    "end_date": p.end_date,
                    "budget": p.budget,
                    "location": p.location,
                    "progress": p.progress,
                    "project_manager_id": p.project_manager_id,
                    "created_at": p.created_at,
                    "project_manager": pm,
                    "task_count": len(p.tasks) if p.tasks else 0,
                    "team_size": len(p.team_members) if p.team_members else 0,
                }
            )
        return out
    finally:
        db.close()


def project(project_id: int) -> Optional[dict[str, Any]]:
    from app.core.config import settings

    if settings.SEARCH_HYDRATE_FROM_SQL:
        rows = _projects_from_sql()
        for r in rows:
            if r.get("id") == project_id:
                return r
        return None

    row = index_reader.get_indexed(f"project-{project_id}")
    if not row:
        return None
    bundle = _load("task", "team")
    mapped = map_projects([row], bundle["task"], bundle["team"])
    return mapped[0] if mapped else None


def tasks(
    project_id: Optional[int] = None,
    status_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = map_tasks(index_reader.list_indexed("task"))
    if project_id is not None:
        rows = [r for r in rows if r.get("project_id") == project_id]
    if status_filter:
        rows = [r for r in rows if r.get("status") == status_filter]
    return rows


def documents(
    project_id: Optional[int] = None,
    file_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = map_documents(index_reader.list_indexed("document"))
    if project_id is not None:
        rows = [r for r in rows if r.get("project_id") == project_id]
    if file_type and file_type != "All":
        rows = [r for r in rows if (r.get("file_type") or "").upper() == file_type.upper()]
    return rows


def team_members() -> list[dict[str, Any]]:
    return map_team(index_reader.list_indexed("team"))


def handover() -> list[dict[str, Any]]:
    return map_handover(index_reader.list_indexed("handover"))


def drawings() -> list[dict[str, Any]]:
    return map_drawings(index_reader.list_indexed("drawing"))


def safety_incidents() -> list[dict[str, Any]]:
    return map_safety_incidents(index_reader.list_indexed("safety"))


def safety_metrics() -> dict[str, Any]:
    return kpi_metadata("safety-kpi-summary", index_reader.get_kpi_item("safety-kpi-summary"))


def attendance() -> list[dict[str, Any]]:
    return map_attendance(index_reader.list_indexed("attendance"))


def timeline() -> list[dict[str, Any]]:
    rows = index_reader.list_indexed("timeline")
    phase_rows = [r for r in rows if r["id"].startswith("timeline-")]
    return map_timeline(phase_rows)


def budget_reports() -> list[dict[str, Any]]:
    return map_budget_reports(index_reader.list_indexed("report"))


def budget_summary() -> dict[str, Any]:
    return kpi_metadata("budget-summary", index_reader.get_kpi_item("budget-summary"))


def productivity() -> dict[str, Any]:
    return kpi_metadata("reports-productivity", index_reader.get_kpi_item("reports-productivity"))


def site_activity() -> dict[str, Any]:
    return kpi_metadata("dashboard-site-activity", index_reader.get_kpi_item("dashboard-site-activity"))


def milestones() -> list[dict[str, Any]]:
    rows = index_reader.list_indexed("timeline")
    milestone_rows = [r for r in rows if r["id"].startswith("dashboard-milestone-")]
    return map_milestones(milestone_rows)

