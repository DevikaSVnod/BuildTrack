"""Load all read-only page data from Azure AI Search (SQL indexer output)."""
from __future__ import annotations

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


def _load(*types: str) -> dict[str, list[dict[str, Any]]]:
    return {t: index_reader.list_indexed(t) for t in types}


def projects(status_filter: Optional[str] = None) -> list[dict[str, Any]]:
    bundle = _load("project", "task", "team")
    rows = map_projects(bundle["project"], bundle["task"], bundle["team"])
    if status_filter and status_filter != "all":
        rows = [r for r in rows if r.get("status") == status_filter]
    return rows


def project(project_id: int) -> Optional[dict[str, Any]]:
    row = index_reader.get_indexed(f"project-{project_id}")
    if not row:
        return None
    bundle = _load("project", "task", "team")
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
