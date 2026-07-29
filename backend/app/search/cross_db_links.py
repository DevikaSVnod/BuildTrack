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
        return merged

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

    return out
