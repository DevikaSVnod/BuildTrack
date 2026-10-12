"""Orchestrate schema search → SQL generate → validate → execute."""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core.config import settings
from app.schema_catalog.search import search_relevant_tables
from app.schema_catalog.snapshot import load_current_snapshot
from app.sql_agent.executor import execute_readonly_sql
from app.sql_agent.generator import generate_select_sql
from app.sql_agent.validator import validate_select_sql

logger = logging.getLogger(__name__)


def looks_structured_db_query(query: str) -> bool:
    """Heuristic: prefer schema-SQL for list/filter/count style questions."""
    q = (query or "").lower().strip()
    if not q:
        return False
    if re.search(
        r"\b("
        r"list|show|how many|count|all|where|status|between|after|before|"
        r"scheduled|in\s+\w+|for\s+event|attendees?|tasks?|projects?|"
        r"locations?|sublocations?|users?|employees?|nominations?|"
        r"documents?|attachments?|files?|labou?r|contractors?|"
        r"attendance|incidents?|accidents?|hse|reviews?|"
        r"companies|vendors?|bids?|tenders?|submissions?|contracts?|"
        r"disputes?|notifications?|alerts?|dashboard|holidays?|"
        r"analytics|overtime|ot\s+hours|odd\s+punches"
        r")\b",
        q,
    ):
        return True
    # Short keyword phrases still ok for SQL if they match known domains
    if re.search(
        r"\b(event|events|agenda|meeting|meetings|project|projects|lms|"
        r"person of the month|potm|user|users|dms|document|documents|"
        r"attachment|attachments|labour|labor|contractor|attendance|"
        r"incident|incidents|hse|occupational|environmental|"
        r"company|vendor|bid|tender|bms|cms|contract|dispute|"
        r"submission|checkpoint|checklist|notification|dashboard|pnl|"
        r"analytics|overtime|ot)\b",
        q,
    ):
        return True
    return False


def looks_free_text_content_query(query: str) -> bool:
    """Prefer data index for longer phrase / note-like searches."""
    q = (query or "").strip()
    if len(q.split()) >= 5 and not re.search(
        r"\b(list|show|how many|count|all events)\b", q.lower()
    ):
        return True
    return False


def _safe_sql_literal(value: str) -> str:
    """Escape a short alphanumeric code for inline SQL literals."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value or ""):
        raise ValueError("unsafe SQL literal")
    return value.replace("'", "''")


def _try_bms_code_lookup(
    query: str,
    *,
    top_k: int,
) -> Optional[dict[str, Any]]:
    """Deterministic BMS ProjectBD lookup — avoids LLM join mistakes."""
    from app.search.query_intel import extract_space_project_code, is_bms_domain_query

    if not is_bms_domain_query(query):
        return None
    code = extract_space_project_code(query)
    if not code:
        return None

    safe = _safe_sql_literal(code)
    sql = (
        f"SELECT TOP ({int(top_k)}) ProjectBDID, ProjectName, ProjectTempCode, "
        f"ProjectSAPCode, ProjectStage, LocationDetails, ContractValue, IsActive "
        f"FROM bms.[ProjectBD] WHERE ISNULL(IsActive, 1) = 1 AND "
        f"(ProjectTempCode = '{safe}' OR ProjectSAPCode = '{safe}')"
    )
    try:
        hits = execute_readonly_sql(
            sql,
            source_id="space-bms",
            source_label="Space BMS",
            content_type="bms_project",
            max_rows=top_k,
        )
    except Exception as exc:
        logger.warning("BMS code lookup failed for %s: %s", code, exc)
        return None

    meta: dict[str, Any] = {
        "sql": sql,
        "retrieval": "schema_sql",
        "tables": ["ProjectBD"],
        "tables_used": ["bms.ProjectBD"],
        "rationale": f"BMS code lookup for {code}",
        "project_code": code,
    }
    if hits:
        return {"hits": hits[:top_k], "meta": meta}

    # No BMS row — fall back to Space Project master with same code.
    proj_sql = (
        f"SELECT TOP ({int(top_k)}) ProjectId, Code, Name, StatusId, IsActive "
        f"FROM project.[Project] WHERE Code = '{safe}'"
    )
    try:
        proj_hits = execute_readonly_sql(
            proj_sql,
            source_id="space-project",
            source_label="Space Project",
            content_type="space_project",
            max_rows=top_k,
        )
    except Exception as exc:
        logger.warning("Space Project code fallback failed for %s: %s", code, exc)
        return {"hits": [], "meta": {**meta, "bms_miss": True, "project_code": code}}

    for h in proj_hits:
        meta_h = dict(h.get("metadata") or {})
        meta_h["bms_fallback"] = True
        meta_h["note"] = (
            f"No BMS ProjectBD row for code {code}; showing Space Project master."
        )
        h["metadata"] = meta_h

    return {
        "hits": proj_hits[:top_k],
        "meta": {
            **meta,
            "bms_miss": True,
            "fallback_source": "space-project",
            "project_code": code,
        },
    }


def run_schema_sql_retrieval(
    query: str,
    *,
    top_k: int = 8,
    source_id: str = "space",
) -> dict[str, Any]:
    """
    Returns {
      hits: list[search hit dicts],
      meta: {tables, sql, rationale, error?}
    }
    """
    if not settings.SCHEMA_SQL_ENABLED:
        return {"hits": [], "meta": {"skipped": True, "reason": "SCHEMA_SQL_ENABLED=false"}}

    if source_id == "space-bms":
        fast = _try_bms_code_lookup(query, top_k=top_k)
        if fast is not None:
            return fast

    snap = load_current_snapshot(source_id)
    if snap is None:
        return {
            "hits": [],
            "meta": {"error": "No schema snapshot — sync schema catalog first"},
        }

    tables = search_relevant_tables(
        query, top_k=settings.SCHEMA_SQL_TOP_TABLES, source_id=source_id
    )
    if not tables:
        return {"hits": [], "meta": {"error": "No relevant tables found in schema catalog"}}

    gen = generate_select_sql(
        query,
        tables,
        database_name=snap.database_name,
        max_rows=min(top_k * 3, settings.SCHEMA_SQL_MAX_ROWS),
    )
    if gen.get("error"):
        return {"hits": [], "meta": {"error": gen["error"], "tables": [t.name for t in tables]}}

    validated = validate_select_sql(
        str(gen.get("sql") or ""),
        tables,
        max_rows=settings.SCHEMA_SQL_MAX_ROWS,
        database_name=snap.database_name,
    )
    if not validated.ok:
        return {
            "hits": [],
            "meta": {
                "error": validated.error,
                "sql_rejected": gen.get("sql"),
                "tables": [t.name for t in tables],
            },
        }

    try:
        hits = execute_readonly_sql(
            validated.sql,
            source_id=snap.source_id,
            source_label=snap.source_label,
            max_rows=settings.SCHEMA_SQL_MAX_ROWS,
        )
    except Exception as exc:
        return {
            "hits": [],
            "meta": {
                "error": f"Execution failed: {exc}",
                "sql": validated.sql,
                "tables": [t.name for t in tables],
            },
        }

    return {
        "hits": hits[:top_k],
        "meta": {
            "sql": validated.sql,
            "rationale": gen.get("rationale"),
            "tables": [t.name for t in tables],
            "tables_used": gen.get("tables_used"),
            "retrieval": "schema_sql",
        },
    }
