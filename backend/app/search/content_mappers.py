"""Map Azure AI Search rows (SQL indexer) to API response shapes."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional


def _numeric_id(index_id: str, prefix: str) -> int:
    raw = index_id.replace(prefix, "", 1)
    try:
        return int(raw)
    except ValueError:
        return 0


def _now_iso() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_user_role(role: str) -> str:
    if role in ("Admin", "Project Manager", "Site Engineer", "Contractor"):
        return role
    key = (role or "").lower().replace(" ", "_")
    return {
        "admin": "Admin",
        "project_manager": "Project Manager",
        "site_engineer": "Site Engineer",
        "contractor": "Contractor",
    }.get(key, "Site Engineer")


def _normalize_project_status(status: str) -> str:
    key = (status or "planning").lower().replace("_", " ")
    return {
        "planning": "Planning",
        "in progress": "In Progress",
        "completed": "Completed",
        "on hold": "On Hold",
    }.get(key, status or "Planning")


def _status_map_task(status: str) -> str:
    m = {
        "todo": "To Do",
        "in_progress": "In Progress",
        "review": "Review",
        "done": "Done",
    }
    return m.get((status or "").lower().replace(" ", "_"), status or "To Do")


def map_projects(
    project_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    team_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    task_counts: dict[int, int] = {}
    for t in task_rows:
        pid = t.get("metadata", {}).get("project_id")
        if pid is not None:
            task_counts[int(pid)] = task_counts.get(int(pid), 0) + 1

    team_counts: dict[int, int] = {}
    for m in team_rows:
        meta = m.get("metadata", {})
        uid = meta.get("user_id")
        projects = meta.get("projects") or []
        if isinstance(projects, str):
            projects = [p.strip() for p in projects.split(",") if p.strip()]
        for pname in projects:
            for p in project_rows:
                if p.get("title") == pname:
                    pid = _numeric_id(p["id"], "project-")
                    team_counts[pid] = team_counts.get(pid, 0) + 1
                    break

    out: list[dict[str, Any]] = []
    for row in project_rows:
        meta = row.get("metadata", {})
        pid = _numeric_id(row["id"], "project-")
        status = _normalize_project_status(str(meta.get("status") or "Planning"))
        out.append({
            "id": pid,
            "name": row.get("title", ""),
            "description": meta.get("description") or _extract_description(row.get("content", ""), row.get("title", "")),
            "status": status,
            "start_date": meta.get("start_date"),
            "end_date": meta.get("end_date"),
            "budget": float(meta["budget"]) if meta.get("budget") is not None else None,
            "location": meta.get("location"),
            "progress": int(meta.get("progress") or 0),
            "project_manager_id": None,
            "created_at": _now_iso(),
            "project_manager": None,
            "task_count": task_counts.get(pid, 0),
            "team_size": team_counts.get(pid, 0),
        })
    return out


def _extract_description(content: str, title: str) -> str:
    text = content.replace(title, "", 1).strip()
    return text[:500] if text else ""


def map_tasks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        meta = row.get("metadata", {})
        tid = meta.get("task_id") or _numeric_id(row["id"], "task-")
        status = _status_map_task(str(meta.get("status", "To Do")))
        priority = meta.get("priority") or "Medium"
        if isinstance(priority, str):
            priority = priority.capitalize()
        assignee = meta.get("assignee")
        out.append({
            "id": int(tid),
            "title": row.get("title", ""),
            "description": "",
            "status": status,
            "priority": priority,
            "project_id": meta.get("project_id"),
            "project_name": meta.get("project_name"),
            "assignee_id": None,
            "assignee": None,
            "due_date": meta.get("due_date"),
            "created_at": _now_iso(),
        })
    return out


def map_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        meta = row.get("metadata", {})
        did = meta.get("doc_id") or _numeric_id(row["id"], "document-")
        uploader = meta.get("uploader")
        out.append({
            "id": int(did),
            "name": row.get("title", ""),
            "file_type": meta.get("file_type"),
            "file_url": meta.get("file_url"),
            "project_id": meta.get("project_id"),
            "project_name": meta.get("project_name"),
            "uploaded_by": None,
            "uploader": None,
            "file_size": int(meta.get("file_size") or 0),
            "created_at": meta.get("upload_date") or _now_iso(),
        })
    return out


def map_team(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per workforce user from indexed workforce docs."""
    seen: set[int] = set()
    out = []
    for row in rows:
        if not row["id"].startswith("workforce-"):
            continue
        meta = row.get("metadata", {})
        uid = int(meta.get("user_id") or _numeric_id(row["id"], "workforce-"))
        if uid in seen:
            continue
        seen.add(uid)
        projects = meta.get("projects") or []
        if isinstance(projects, str):
            projects = [p.strip() for p in projects.split(",") if p.strip()]
        project_name = projects[0] if projects else None
        email = meta.get("email") or f"user{uid}@buildtrack.com"
        role = _normalize_user_role(str(meta.get("role") or "Site Engineer"))
        out.append({
            "id": uid,
            "user_id": uid,
            "project_id": None,
            "project_name": project_name,
            "role": role,
            "joined_at": _now_iso(),
            "user": {
                "id": uid,
                "full_name": row.get("title", ""),
                "email": email,
                "role": role,
                "is_active": True,
                "created_at": _now_iso(),
            },
            "active_projects_count": len(projects),
            "tasks_count": 0,
        })
    return out


def map_handover(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": m.get("metadata", {}).get("doc_id") or _numeric_id(r["id"], "handover-"),
            "title": r.get("title", ""),
            "category": m.get("category"),
            "project": m.get("project"),
            "status": m.get("status"),
            "signedBy": m.get("signed_by") or "—",
            "date": "—",
        }
        for r in rows
        for m in [r.get("metadata", {})]
    ]


def map_drawings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": m.get("drawing_id") or _numeric_id(r["id"], "drawing-"),
            "drawingNo": m.get("drawing_no"),
            "title": r.get("title", ""),
            "discipline": m.get("discipline"),
            "rev": m.get("revision"),
            "project": m.get("project"),
            "status": m.get("status"),
            "uploadedBy": m.get("uploaded_by"),
        }
        for r in rows
        for m in [r.get("metadata", {})]
    ]


def map_safety_incidents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": m.get("inc_id") or _numeric_id(r["id"], "safety-"),
            "date": m.get("incident_date"),
            "type": m.get("incident_type") or r.get("title", ""),
            "description": _incident_description(r.get("content", "")),
            "project": m.get("project"),
            "severity": m.get("severity"),
            "status": m.get("status"),
            "reportedBy": m.get("reported_by"),
        }
        for r in rows
        for m in [r.get("metadata", {})]
    ]


def _incident_description(content: str) -> str:
    return content[:200] if content else ""


def map_attendance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": _numeric_id(r["id"], "attendance-"),
            "name": m.get("name"),
            "role": m.get("role"),
            "status": m.get("status"),
            "project": m.get("project"),
        }
        for r in rows
        for m in [r.get("metadata", {})]
    ]


def map_timeline(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": _numeric_id(r["id"], "timeline-"),
            "project": m.get("project"),
            "phase": m.get("phase"),
            "start": m.get("start"),
            "end": m.get("end"),
            "status": m.get("status"),
            "progress": m.get("progress"),
        }
        for r in rows
        for m in [r.get("metadata", {})]
    ]


def map_budget_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if r["id"] in ("budget-summary",) or not r["id"].startswith("budget-"):
            continue
        m = r.get("metadata", {})
        if m.get("category") and m.get("category") != "Budget":
            continue
        budget_cr = float(m.get("budget_cr") or 0)
        spent_cr = float(m.get("spent_cr") or 0)
        if budget_cr <= 0:
            continue
        util = int(m.get("utilization_pct") or 0)
        if not util and budget_cr:
            util = round(spent_cr / budget_cr * 100)
        out.append({
            "project": m.get("project") or r.get("title", "").replace("Budget – ", ""),
            "budget_cr": budget_cr,
            "spent_cr": spent_cr,
            "utilization_pct": util,
        })
    return out


def map_milestones(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": r.get("title", ""),
            "due": m.get("due", ""),
            "priority": m.get("priority", "Medium"),
        }
        for r in rows
        if r["id"].startswith("dashboard-milestone-")
        for m in [r.get("metadata", {})]
    ]


def kpi_metadata(item_id: str, row: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not row:
        return {}
    return row.get("metadata") or {}
