"""Workforce search results from Azure AI Search (SQL indexer output)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.search import content_service


def _matches_project(projects: list[str], qualifier: str) -> bool:
    qual_lower = qualifier.lower()
    for pname in projects:
        pl = pname.lower()
        if qual_lower in pl or pl in qual_lower:
            return True
    qual_words = set(qual_lower.split())
    for pname in projects:
        if qual_words & set(pname.lower().split()):
            return True
    return False


def workforce_results_from_db(
    _db,
    project_qualifier: Optional[str] = None,
) -> List[Dict[str, Any]]:
    members = content_service.team_members()
    results: List[Dict[str, Any]] = []
    for m in members:
        user = m.get("user") or {}
        projects: list[str] = []
        if m.get("project_name"):
            projects.append(str(m["project_name"]))
        if project_qualifier and projects and not _matches_project(projects, project_qualifier):
            continue
        uid = m.get("user_id")
        results.append({
            "id": f"workforce-{uid}",
            "title": user.get("full_name") or m.get("role") or "Team member",
            "snippet": f"{user.get('full_name', '')} {m.get('role', '')} {', '.join(projects)}"[:220],
            "content_type": "team",
            "url": f"/team?userId={uid}",
            "metadata": {
                "role": m.get("role"),
                "email": user.get("email"),
                "user_id": uid,
                "projects": projects,
            },
            "score": 1.0,
        })
    return results
