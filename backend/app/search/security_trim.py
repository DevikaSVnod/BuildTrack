"""Query-time security trimming for Azure AI Search OData filters."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def allowed_project_ids(user: Any, db: Any = None) -> Optional[list[int]]:
    """
    Return project ids the user may see, or None for unrestricted (admin).
    """
    if user is None:
        return None
    role = getattr(user, "role", None)
    role_val = str(getattr(role, "value", role) or "").lower()
    if role_val in {"admin", "project_manager"}:
        return None
    if db is None:
        return []
    try:
        from app.models.team import TeamMember
        from app.models.project import Project

        member_ids = [
            r.project_id
            for r in db.query(TeamMember.project_id)
            .filter(TeamMember.user_id == user.id)
            .all()
            if r.project_id is not None
        ]
        managed = [
            r.id
            for r in db.query(Project.id)
            .filter(Project.project_manager_id == user.id)
            .all()
        ]
        return sorted(set(member_ids + managed))
    except Exception as exc:
        logger.warning("ACL project lookup failed: %s", exc)
        return []


def build_security_odata(user: Any, db: Any = None) -> Optional[str]:
    """
    OData filter fragment restricting hits by project_id.
    Returns None when trimming disabled or user is unrestricted.
    """
    if not settings.SEARCH_SECURITY_TRIMMING:
        return None
    projects = allowed_project_ids(user, db)
    if projects is None:
        return None
    if not projects:
        # No access — filter that matches nothing
        return "project_id eq '___none___'"
    # project_id stored as string on discovery docs
    parts = [f"project_id eq '{pid}'" for pid in projects]
    return "(" + " or ".join(parts) + ")"


def merge_odata(base: Optional[str], security: Optional[str]) -> Optional[str]:
    if base and security:
        return f"({base}) and ({security})"
    return base or security
