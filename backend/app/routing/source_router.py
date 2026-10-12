"""Keyword + light semantic source router (DB / TOOL / BOTH)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.routing.tool_catalog import list_tools, match_tools

SourceKind = Literal["DB", "TOOL", "BOTH"]

_TOOL_KEYWORDS = (
    "weather",
    "temperature",
    "forecast",
    "humidity",
    "calendar",
    "email",
    "send mail",
    "upload",
    "download",
    "slack",
    "teams message",
)

_DB_KEYWORDS = (
    "event",
    "events",
    "agenda",
    "meeting",
    "meetings",
    "attendee",
    "project",
    "projects",
    "document",
    "documents",
    "task",
    "tasks",
    "user",
    "users",
    "employee",
    "employees",
    "person of the month",
    "potm",
    "nomination",
    "dms",
    "document",
    "documents",
    "attachment",
    "attachments",
    "labour",
    "labor",
    "attendance",
    "contractor",
    "hse",
    "incident",
    "incidents",
    "accident",
    "company",
    "vendor",
    "bid",
    "tender",
    "bms",
    "cms",
    "contract",
    "dispute",
    "submission",
    "checkpoint",
    "notification",
    "dashboard",
    "analytics",
    "overtime",
    "list",
    "show",
    "how many",
    "count",
    "status",
    "scheduled",
    "database",
    "sql",
    "table",
)


@dataclass
class RouteDecision:
    source: SourceKind
    confidence: float
    db_score: float
    tool_score: float
    reasons: list[str]


def route_query(query: str) -> RouteDecision:
    q = (query or "").lower().strip()
    reasons: list[str] = []
    tool_score = 0.0
    db_score = 0.0

    for kw in _TOOL_KEYWORDS:
        if kw in q:
            tool_score += 2.5
            reasons.append(f"tool-keyword:{kw}")
    for kw in _DB_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", q):
            db_score += 2.0
            reasons.append(f"db-keyword:{kw}")

    # Tool catalog overlap
    matched_tools = match_tools(q)
    if matched_tools:
        tool_score += 1.5 * len(matched_tools)
        reasons.append("tool-catalog-match")

    # Schema catalog soft semantic: table/hint overlap across Space DBs
    from app.schema_catalog.snapshot import list_current_snapshots

    for snap in list_current_snapshots():
        for t in snap.tables:
            blob = f"{t.name} {t.description} {' '.join(t.search_hints)}".lower()
            hit = False
            for token in re.findall(r"[a-z0-9_]{3,}", q):
                if token in blob:
                    db_score += 0.6
                    hit = True
            if hit:
                reasons.append(f"schema-hint:{snap.source_id}:{t.name}")

    # Defaults when nothing matched
    if db_score == 0 and tool_score == 0:
        db_score = 1.0
        reasons.append("default-db")

    if tool_score >= db_score + 1.5 and tool_score >= 2.0:
        source: SourceKind = "TOOL"
    elif db_score >= tool_score + 1.5 and db_score >= 2.0:
        source = "DB"
    elif tool_score >= 2.0 and db_score >= 2.0:
        source = "BOTH"
    elif tool_score > db_score:
        source = "TOOL"
    else:
        source = "DB"

    total = db_score + tool_score + 1e-6
    confidence = abs(db_score - tool_score) / total
    return RouteDecision(
        source=source,
        confidence=round(min(1.0, confidence + 0.35), 3),
        db_score=round(db_score, 3),
        tool_score=round(tool_score, 3),
        reasons=reasons[:12],
    )
