"""Validate LLM-generated SQL before execution."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.schema_catalog.models import TableInfo

_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|merge|drop|alter|create|truncate|exec|execute|"
    r"xp_|sp_|grant|revoke|deny|backup|restore|shutdown|openrowset|opendatasource|"
    r"into\s+outfile|bulk\s+insert"
    r")\b",
    re.IGNORECASE,
)
_MULTI_STMT = re.compile(r";\s*\S")
_COMMENT = re.compile(r"(--|/\*|\*/)")


@dataclass
class ValidationResult:
    ok: bool
    sql: str = ""
    error: str = ""


def _bracket(name: str) -> str:
    return f"[{name.replace(']', '')}]"


def _strip_database_name_prefix(sql: str, database_name: str) -> str:
    """LLM sometimes emits DB.schema.table — strip the database qualifier."""
    db = (database_name or "").strip()
    if not db:
        return sql
    escaped = re.escape(db)
    return re.sub(
        rf"(?i)(?:\[{escaped}\]|{escaped})\s*\.\s*",
        "",
        sql,
    )


def validate_select_sql(
    sql: str,
    allowed_tables: list[TableInfo],
    *,
    max_rows: Optional[int] = None,
    database_name: str = "",
) -> ValidationResult:
    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return ValidationResult(ok=False, error="Empty SQL")

    raw = _strip_database_name_prefix(raw, database_name)

    if _COMMENT.search(raw):
        return ValidationResult(ok=False, error="SQL comments are not allowed")
    if _MULTI_STMT.search(raw):
        return ValidationResult(ok=False, error="Multiple SQL statements are not allowed")
    if _FORBIDDEN.search(raw):
        return ValidationResult(ok=False, error="Only read-only SELECT queries are allowed")

    # Must start with SELECT or WITH ... SELECT
    head = re.sub(r"\s+", " ", raw.lstrip()).lower()
    if not (head.startswith("select") or head.startswith("with ")):
        return ValidationResult(ok=False, error="SQL must be a SELECT (or WITH ... SELECT)")

    allow_map = {t.name.lower(): t for t in allowed_tables}
    allow_schema = {t.schema_name.lower() for t in allowed_tables if t.schema_name}

    # Extract referenced table-ish tokens after FROM/JOIN (1–3 part names)
    table_refs = re.findall(
        r"\b(?:from|join)\s+((?:\[?[A-Za-z0-9_]+\]?\.){0,2}\[?[A-Za-z0-9_]+\]?)",
        raw,
        flags=re.IGNORECASE,
    )
    if not table_refs:
        return ValidationResult(ok=False, error="SQL must reference a FROM/JOIN table")

    for ref in table_refs:
        parts = [p.strip("[]") for p in ref.split(".")]
        if len(parts) >= 3:
            # db.schema.table — after strip should be rare; treat last two as schema.table
            schema, tname = parts[-2].lower(), parts[-1].lower()
        elif len(parts) == 2:
            schema, tname = parts[0].lower(), parts[1].lower()
        else:
            tname = parts[0].lower()
            schema = ""
            if tname not in allow_map and tname not in {"dbo"}:
                return ValidationResult(
                    ok=False, error=f"Table '{parts[0]}' is not in the allowlist"
                )
            continue

        if schema not in allow_schema:
            return ValidationResult(
                ok=False, error=f"Schema '{schema}' is not allowed"
            )
        if tname not in allow_map:
            return ValidationResult(
                ok=False, error=f"Table '{parts[-1]}' is not in the allowlist"
            )

    # Column allowlist soft-check: reject clear unknown schema.table.column patterns
    # (full SQL parsing is out of scope; table allowlist + SELECT-only is the hard gate)

    limit = max_rows or settings.SCHEMA_SQL_MAX_ROWS or 50
    # Force TOP if missing (T-SQL)
    if not re.search(r"\bselect\s+top\s*\(", raw, flags=re.IGNORECASE) and not re.search(
        r"\bselect\s+top\s+\d+", raw, flags=re.IGNORECASE
    ):
        raw = re.sub(
            r"(?i)^\s*select\s+",
            f"SELECT TOP ({int(limit)}) ",
            raw,
            count=1,
        )
    else:
        # Clamp TOP (n) if larger than limit
        def _clamp_top(m: re.Match) -> str:
            n = int(m.group(1))
            return f"SELECT TOP ({min(n, int(limit))})"

        raw = re.sub(
            r"(?i)select\s+top\s*\(\s*(\d+)\s*\)",
            _clamp_top,
            raw,
            count=1,
        )
        raw = re.sub(
            r"(?i)select\s+top\s+(\d+)",
            lambda m: f"SELECT TOP ({min(int(m.group(1)), int(limit))})",
            raw,
            count=1,
        )

    raw = _ensure_join_key_columns(raw, allowed_tables)
    return ValidationResult(ok=True, sql=raw)


# Columns that enable Space cross-DB linking when present on a table.
_JOIN_KEY_NAMES = (
    "ProjectId",
    "ProjectID",
    "UserId",
    "UserID",
    "DocumentId",
    "DocumentID",
)


def _ensure_join_key_columns(sql: str, allowed_tables: list[TableInfo]) -> str:
    """
    LLM often omits PK / join keys (e.g. SELECT Code, Name, StatusId FROM Project).
    Inject missing ProjectId/UserId/DocumentId and primary keys so executor can
    promote them for cross-DB linking.
    """
    if re.search(r"(?i)\bselect\s+top\s*\([^)]+\)\s*\*", sql) or re.search(
        r"(?i)\bselect\s+\*", sql
    ):
        return sql

    allow_map = {t.name.lower(): t for t in allowed_tables}
    # Prefer the first FROM table (typical list query).
    m = re.search(
        r"\bfrom\s+((?:\[?[A-Za-z0-9_]+\]?\.){0,2}\[?[A-Za-z0-9_]+\]?)",
        sql,
        flags=re.IGNORECASE,
    )
    if not m:
        return sql
    parts = [p.strip("[]") for p in m.group(1).split(".")]
    tname = parts[-1].lower()
    table = allow_map.get(tname)
    if table is None:
        return sql

    col_names = {c.name for c in (table.columns or [])}
    col_lower = {c.name.lower(): c.name for c in (table.columns or [])}

    wanted: list[str] = []
    for pk in table.primary_keys or []:
        if pk in col_names:
            wanted.append(pk)
    for key in _JOIN_KEY_NAMES:
        real = col_lower.get(key.lower())
        if real and real not in wanted:
            wanted.append(real)

    if not wanted:
        return sql

    sql_lower = sql.lower()
    missing = [c for c in wanted if f"[{c.lower()}]" not in sql_lower and not re.search(
        rf"(?i)(?<![A-Za-z0-9_]){re.escape(c)}(?![A-Za-z0-9_])", sql
    )]
    if not missing:
        return sql

    insert = ", ".join(_bracket(c) for c in missing) + ", "

    def _inject(match: re.Match) -> str:
        return match.group(0) + insert

    # After SELECT TOP (n) or SELECT TOP n
    updated, n = re.subn(
        r"(?i)^(select\s+top\s*\(\s*\d+\s*\)\s+)",
        _inject,
        sql,
        count=1,
    )
    if n:
        return updated
    updated, n = re.subn(
        r"(?i)^(select\s+top\s+\d+\s+)",
        _inject,
        sql,
        count=1,
    )
    if n:
        return updated
    updated, n = re.subn(
        r"(?i)^(select\s+)",
        _inject,
        sql,
        count=1,
    )
    return updated if n else sql
