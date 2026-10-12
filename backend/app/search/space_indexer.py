"""
Push Space Action SQL rows into a dedicated Azure AI Search index.

Connection: SPACE_DATABASE_URL → DEV_V1_SPACE_ACTION
Index: AZURE_SEARCH_SPACE_INDEX (space-action-index)

Indexing strategy:
  - Dynamically discover all tables in schema `action`
  - Exclude OfflineSyncLog and Synonyms_Configuration
  - Keep richer builders for Events / Event_Agenda / Event_Information
  - Generic column-aware indexing for every other discovered table
  - Search uses the Azure index (no per-query SQL fan-out across tables)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.search.indexer import ensure_index_exists, get_search_client, index_documents

logger = logging.getLogger(__name__)

SOURCE_ID = "space"
SOURCE_LABEL = "Space Action"
SOURCE_DB_NAME = "DEV_V1_SPACE_ACTION"
SPACE_SCHEMA = "action"

# Never index these (large / non-searchable operational tables).
EXCLUDED_TABLES = frozenset({"OfflineSyncLog", "Synonyms_Configuration"})

# Keep existing high-quality builders for these; still counted as discovered.
SPECIAL_TABLES = frozenset({"Events", "Event_Agenda", "Event_Information"})

_TEXT_TYPES = frozenset(
    {"nvarchar", "varchar", "nchar", "char", "text", "ntext", "xml", "sysname"}
)
_SKIP_TYPES = frozenset(
    {
        "image",
        "varbinary",
        "binary",
        "timestamp",
        "rowversion",
        "geography",
        "geometry",
        "hierarchyid",
        "sql_variant",
    }
)

# Cap per-table rows to protect indexing cost; raise via env if needed.
_DEFAULT_MAX_ROWS = 25_000
_MAX_TEXT_CHARS = 2_000
_MAX_CONTENT_CHARS = 8_000


def space_index_name() -> str:
    return settings.AZURE_SEARCH_SPACE_INDEX or "space-action-index"


def space_database_url() -> str:
    url = (settings.SPACE_DATABASE_URL or "").strip()
    if not url:
        raise RuntimeError(
            "SPACE_DATABASE_URL is not set — add the Space SQL connection string to backend/.env"
        )
    return url


def _fmt_dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    return str(value)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text_val = str(value).strip()
    return text_val


def _meta_json(meta: dict[str, Any]) -> str:
    payload = {
        **meta,
        "database_id": SOURCE_ID,
        "database_label": SOURCE_LABEL,
        "source_db": SOURCE_DB_NAME,
        "database": SOURCE_DB_NAME,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _space_engine():
    from scripts.setup_assets_db import create_mssql_engine

    return create_mssql_engine(space_database_url())


def _safe_ident(name: str) -> str:
    """Allow only simple SQL identifiers (no injection via dynamic names)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def _bracket(name: str) -> str:
    return f"[{_safe_ident(name)}]"


def _content_type_for_table(table: str) -> str:
    # Preserve existing content_type values for special tables.
    mapping = {
        "Events": "event",
        "Event_Agenda": "event_agenda",
        "Event_Information": "event_information",
    }
    if table in mapping:
        return mapping[table]
    # event_task, event_attendee, …
    return re.sub(r"[^a-z0-9]+", "_", table.lower()).strip("_")


def discover_action_tables(db) -> tuple[list[str], list[str]]:
    """
    Return (included_tables, excluded_tables) under schema `action`.
    """
    rows = db.execute(
        text(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = :schema
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """
        ),
        {"schema": SPACE_SCHEMA},
    ).fetchall()
    all_names = [str(r[0]) for r in rows]
    excluded = [n for n in all_names if n in EXCLUDED_TABLES]
    included = [n for n in all_names if n not in EXCLUDED_TABLES]
    logger.info(
        "Space schema [%s] discovered %s table(s): %s",
        SPACE_SCHEMA,
        len(all_names),
        ", ".join(all_names) or "(none)",
    )
    if excluded:
        logger.info(
            "Space schema [%s] excluded %s table(s): %s",
            SPACE_SCHEMA,
            len(excluded),
            ", ".join(excluded),
        )
    logger.info(
        "Space schema [%s] will index %s table(s): %s",
        SPACE_SCHEMA,
        len(included),
        ", ".join(included) or "(none)",
    )
    return included, excluded


def _table_columns(db, table: str) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
            ORDER BY ORDINAL_POSITION
            """
        ),
        {"schema": SPACE_SCHEMA, "table": table},
    ).mappings().all()
    return [dict(r) for r in rows]


def _primary_key_columns(db, table: str) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
            INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
               AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
               AND tc.TABLE_NAME = ku.TABLE_NAME
            WHERE tc.TABLE_SCHEMA = :schema
              AND tc.TABLE_NAME = :table
              AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ORDER BY ku.ORDINAL_POSITION
            """
        ),
        {"schema": SPACE_SCHEMA, "table": table},
    ).fetchall()
    return [str(r[0]) for r in rows]


def _pick_title_column(columns: list[dict[str, Any]], pk_cols: list[str]) -> Optional[str]:
    names = [c["COLUMN_NAME"] for c in columns]
    preferred = (
        "Title",
        "Name",
        "Agenda",
        "Subject",
        "Description",
        "EventNumber",
        "DimensionType",
        "Tag",
        "Note",
        "OpeningNote",
        "ClosingNote",
        "Information",
        "Location",
    )
    for cand in preferred:
        if cand in names:
            return cand
    # First short text column that is not a PK
    for c in columns:
        dtype = str(c["DATA_TYPE"] or "").lower()
        name = c["COLUMN_NAME"]
        if name in pk_cols:
            continue
        if dtype in _TEXT_TYPES:
            maxlen = c.get("CHARACTER_MAXIMUM_LENGTH")
            if maxlen is None or maxlen < 0 or maxlen <= 500:
                return name
    return pk_cols[0] if pk_cols else (names[0] if names else None)


def _searchable_columns(columns: list[dict[str, Any]], pk_cols: list[str]) -> list[str]:
    """Tier-1 text fields only — never embed every column type."""
    out: list[str] = []
    for c in columns:
        name = c["COLUMN_NAME"]
        dtype = str(c["DATA_TYPE"] or "").lower()
        if dtype in _SKIP_TYPES:
            continue
        if dtype not in _TEXT_TYPES:
            continue
        # Skip huge MAX columns that are likely blobs of unused text
        maxlen = c.get("CHARACTER_MAXIMUM_LENGTH")
        if maxlen is not None and int(maxlen) == -1 and name.lower().endswith("json"):
            continue
        out.append(name)
    # Always include PK string form in content via metadata, not necessarily as searchable
    return out[:40]


def _max_rows_per_table() -> int:
    try:
        return max(1, int(settings.SPACE_INDEX_MAX_ROWS_PER_TABLE or _DEFAULT_MAX_ROWS))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ROWS


def _load_generic_table_docs(db, table: str) -> list[dict[str, Any]]:
    """Column-aware indexing for one action.* table."""
    _safe_ident(table)
    columns = _table_columns(db, table)
    if not columns:
        logger.warning("Space table %s.%s has no columns — skipped", SPACE_SCHEMA, table)
        return []

    pk_cols = _primary_key_columns(db, table)
    if not pk_cols:
        # Fallback: first *Id column or first column
        for c in columns:
            if str(c["COLUMN_NAME"]).lower().endswith("id"):
                pk_cols = [c["COLUMN_NAME"]]
                break
        if not pk_cols:
            pk_cols = [columns[0]["COLUMN_NAME"]]
        logger.info(
            "Space table %s.%s has no PK — using %s",
            SPACE_SCHEMA,
            table,
            ",".join(pk_cols),
        )

    searchable = _searchable_columns(columns, pk_cols)
    title_col = _pick_title_column(columns, pk_cols)
    col_names = [c["COLUMN_NAME"] for c in columns]
    has_is_active = "IsActive" in col_names
    has_is_archived = "IsArchived" in col_names

    select_cols = list(dict.fromkeys([*pk_cols, *searchable, title_col]))
    select_cols = [c for c in select_cols if c]
    select_sql = ", ".join(_bracket(c) for c in select_cols)
    table_sql = f"{_bracket(SPACE_SCHEMA)}.{_bracket(table)}"

    where_parts: list[str] = []
    if has_is_active:
        where_parts.append("ISNULL([IsActive], 1) = 1")
    if has_is_archived:
        where_parts.append("ISNULL([IsArchived], 0) = 0")
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    order_sql = ", ".join(_bracket(c) for c in pk_cols)
    limit = _max_rows_per_table()
    sql = f"""
        SELECT TOP ({int(limit)}) {select_sql}
        FROM {table_sql}
        {where_sql}
        ORDER BY {order_sql}
    """

    rows = db.execute(text(sql)).mappings().all()
    if len(rows) >= limit:
        logger.warning(
            "Space table %s.%s hit row cap (%s) — truncate for cost control",
            SPACE_SCHEMA,
            table,
            limit,
        )

    ctype = _content_type_for_table(table)
    docs: list[dict[str, Any]] = []
    for row in rows:
        pk_parts = [_clean(row.get(c)) for c in pk_cols]
        record_id = "-".join(p for p in pk_parts if p) or "unknown"
        title_val = _clean(row.get(title_col)) if title_col else ""
        if not title_val:
            title_val = f"{table} {record_id}"

        content_bits: list[str] = [
            f"Database: {SOURCE_DB_NAME}",
            f"Table: {SPACE_SCHEMA}.{table}",
            f"Record ID: {record_id}",
        ]
        for col in searchable:
            val = _clean(row.get(col))
            if not val:
                continue
            if len(val) > _MAX_TEXT_CHARS:
                val = val[:_MAX_TEXT_CHARS] + "…"
            content_bits.append(f"{col}: {val}")

        content = "\n".join(content_bits)[:_MAX_CONTENT_CHARS]
        # Azure AI Search keys: letters, digits, underscore, dash, equal
        safe_key = re.sub(r"[^A-Za-z0-9_\-=]", "-", f"space-{table}-{record_id}")[:512]

        docs.append(
            {
                "id": safe_key,
                "title": title_val[:180],
                "content": content,
                "content_type": ctype,
                "url": f"/space/{table}/{record_id}",
                "metadata": _meta_json(
                    {
                        "table": f"{SPACE_SCHEMA}.{table}",
                        "table_name": table,
                        "schema": SPACE_SCHEMA,
                        "record_id": record_id,
                        "primary_key": pk_cols,
                    }
                ),
            }
        )
    return docs


def _load_special_events_docs(db) -> list[dict[str, Any]]:
    """Existing rich builders for Events / Agenda / Information (unchanged shape)."""
    docs: list[dict[str, Any]] = []

    events = db.execute(
        text(
            """
            SELECT EventId, EventNumber, Title, Information, Location,
                   OpeningNote, ClosingNote, ScheduledStartDateTime,
                   ScheduledEndDateTime, IsActive, IsArchived
            FROM action.Events
            WHERE ISNULL(IsActive, 1) = 1 AND ISNULL(IsArchived, 0) = 0
            """
        )
    ).mappings().all()

    agendas = db.execute(
        text(
            """
            SELECT a.EventAgendaId, a.EventId, a.Agenda, a.AddedDate,
                   e.Title AS EventTitle, e.EventNumber
            FROM action.Event_Agenda a
            LEFT JOIN action.Events e ON e.EventId = a.EventId
            WHERE ISNULL(a.IsActive, 1) = 1 AND ISNULL(a.IsArchived, 0) = 0
            """
        )
    ).mappings().all()

    infos = db.execute(
        text(
            """
            SELECT i.EventInformationId, i.EventId, i.DimensionType, i.DimensionId,
                   e.Title AS EventTitle, e.EventNumber
            FROM action.Event_Information i
            LEFT JOIN action.Events e ON e.EventId = i.EventId
            WHERE ISNULL(i.IsActive, 1) = 1 AND ISNULL(i.IsArchived, 0) = 0
            """
        )
    ).mappings().all()

    agendas_by_event: dict[int, list[str]] = {}
    for row in agendas:
        eid = int(row["EventId"] or 0)
        agenda = _clean(row.get("Agenda"))
        if eid and agenda:
            agendas_by_event.setdefault(eid, []).append(agenda)

    dims_by_event: dict[int, list[str]] = {}
    for row in infos:
        eid = int(row["EventId"] or 0)
        dim = _clean(row.get("DimensionType"))
        if eid and dim:
            dims_by_event.setdefault(eid, []).append(f"{dim}:{row.get('DimensionId')}")

    for row in events:
        eid = int(row["EventId"])
        title = _clean(row.get("Title")) or f"Event {eid}"
        number = _clean(row.get("EventNumber"))
        parts = [
            f"Database: {SOURCE_DB_NAME}",
            f"Table: {SPACE_SCHEMA}.Events",
            f"Record ID: {eid}",
            f"Event: {title}",
            f"Event number: {number}" if number else "",
            f"Location: {_clean(row.get('Location'))}",
            f"Information: {_clean(row.get('Information'))}",
            f"Opening note: {_clean(row.get('OpeningNote'))}",
            f"Closing note: {_clean(row.get('ClosingNote'))}",
            f"Scheduled start: {_fmt_dt(row.get('ScheduledStartDateTime'))}",
            f"Scheduled end: {_fmt_dt(row.get('ScheduledEndDateTime'))}",
        ]
        event_agendas = agendas_by_event.get(eid) or []
        if event_agendas:
            parts.append("Agenda items: " + "; ".join(event_agendas[:20]))
        event_dims = dims_by_event.get(eid) or []
        if event_dims:
            parts.append("Dimensions: " + ", ".join(event_dims[:30]))

        content = "\n".join(p for p in parts if p and not p.endswith(": "))
        docs.append(
            {
                "id": f"space-event-{eid}",
                "title": f"{number + ' — ' if number else ''}{title}",
                "content": content,
                "content_type": "event",
                "url": f"/space/events/{eid}",
                "metadata": _meta_json(
                    {
                        "event_id": eid,
                        "record_id": str(eid),
                        "event_number": number,
                        "location": _clean(row.get("Location")),
                        "table": f"{SPACE_SCHEMA}.Events",
                        "table_name": "Events",
                        "schema": SPACE_SCHEMA,
                    }
                ),
            }
        )

    for row in agendas:
        aid = int(row["EventAgendaId"])
        eid = int(row["EventId"] or 0)
        agenda = _clean(row.get("Agenda")) or f"Agenda {aid}"
        event_title = _clean(row.get("EventTitle"))
        event_number = _clean(row.get("EventNumber"))
        content = "\n".join(
            p
            for p in [
                f"Database: {SOURCE_DB_NAME}",
                f"Table: {SPACE_SCHEMA}.Event_Agenda",
                f"Record ID: {aid}",
                f"Event agenda: {agenda}",
                f"Event: {event_title}" if event_title else "",
                f"Event number: {event_number}" if event_number else "",
                f"Event id: {eid}" if eid else "",
                f"Added: {_fmt_dt(row.get('AddedDate'))}",
            ]
            if p
        )
        docs.append(
            {
                "id": f"space-agenda-{aid}",
                "title": agenda[:180],
                "content": content,
                "content_type": "event_agenda",
                "url": f"/space/events/{eid}#agenda-{aid}" if eid else "",
                "metadata": _meta_json(
                    {
                        "event_agenda_id": aid,
                        "record_id": str(aid),
                        "event_id": eid,
                        "event_title": event_title,
                        "table": f"{SPACE_SCHEMA}.Event_Agenda",
                        "table_name": "Event_Agenda",
                        "schema": SPACE_SCHEMA,
                    }
                ),
            }
        )

    for row in infos:
        iid = int(row["EventInformationId"])
        eid = int(row["EventId"] or 0)
        dim_type = _clean(row.get("DimensionType")) or "Dimension"
        event_title = _clean(row.get("EventTitle"))
        event_number = _clean(row.get("EventNumber"))
        title = f"{dim_type} — {event_title or f'Event {eid}'}"
        content = "\n".join(
            p
            for p in [
                f"Database: {SOURCE_DB_NAME}",
                f"Table: {SPACE_SCHEMA}.Event_Information",
                f"Record ID: {iid}",
                f"Event information dimension: {dim_type}",
                f"Dimension id: {row.get('DimensionId')}",
                f"Event: {event_title}" if event_title else "",
                f"Event number: {event_number}" if event_number else "",
                f"Event id: {eid}" if eid else "",
            ]
            if p
        )
        docs.append(
            {
                "id": f"space-eventinfo-{iid}",
                "title": title[:180],
                "content": content,
                "content_type": "event_information",
                "url": f"/space/events/{eid}#info-{iid}" if eid else "",
                "metadata": _meta_json(
                    {
                        "event_information_id": iid,
                        "record_id": str(iid),
                        "event_id": eid,
                        "dimension_type": dim_type,
                        "dimension_id": row.get("DimensionId"),
                        "event_title": event_title,
                        "table": f"{SPACE_SCHEMA}.Event_Information",
                        "table_name": "Event_Information",
                        "schema": SPACE_SCHEMA,
                    }
                ),
            }
        )

    return docs


def load_space_search_docs() -> list[dict[str, Any]]:
    """
    Discover action.* tables and build Azure Search documents.
    Special tables keep rich builders; all others use generic column-aware indexing.
    """
    engine = _space_engine()
    Session = sessionmaker(bind=engine)
    db = Session()
    docs: list[dict[str, Any]] = []
    try:
        included, excluded = discover_action_tables(db)
        # Stash for sync_space_to_azure_search reporting
        load_space_search_docs.last_discovery = {  # type: ignore[attr-defined]
            "discovered": included + excluded,
            "excluded": excluded,
            "included": included,
            "indexed": [],
            "failed": [],
        }

        # 1) Rich path for the three original tables (if present)
        special_present = [t for t in included if t in SPECIAL_TABLES]
        if special_present:
            try:
                special_docs = _load_special_events_docs(db)
                docs.extend(special_docs)
                for t in special_present:
                    load_space_search_docs.last_discovery["indexed"].append(  # type: ignore[attr-defined]
                        {
                            "table": f"{SPACE_SCHEMA}.{t}",
                            "docs": sum(
                                1
                                for d in special_docs
                                if (json.loads(d["metadata"]).get("table_name") == t)
                            ),
                            "mode": "special",
                        }
                    )
                logger.info(
                    "Space special tables indexed OK: %s (%s docs)",
                    ", ".join(special_present),
                    len(special_docs),
                )
            except Exception as exc:
                logger.exception("Space special table indexing failed: %s", exc)
                for t in special_present:
                    load_space_search_docs.last_discovery["failed"].append(  # type: ignore[attr-defined]
                        {"table": f"{SPACE_SCHEMA}.{t}", "error": str(exc)}
                    )

        # 2) Generic path for every other discovered table
        generic_tables = [t for t in included if t not in SPECIAL_TABLES]
        for table in generic_tables:
            try:
                table_docs = _load_generic_table_docs(db, table)
                docs.extend(table_docs)
                load_space_search_docs.last_discovery["indexed"].append(  # type: ignore[attr-defined]
                    {
                        "table": f"{SPACE_SCHEMA}.{table}",
                        "docs": len(table_docs),
                        "mode": "generic",
                    }
                )
                logger.info(
                    "Space table %s.%s indexed OK — %s docs",
                    SPACE_SCHEMA,
                    table,
                    len(table_docs),
                )
            except Exception as exc:
                logger.exception(
                    "Space table %s.%s indexing failed: %s", SPACE_SCHEMA, table, exc
                )
                load_space_search_docs.last_discovery["failed"].append(  # type: ignore[attr-defined]
                    {"table": f"{SPACE_SCHEMA}.{table}", "error": str(exc)}
                )
    finally:
        db.close()
        engine.dispose()

    return docs


load_space_search_docs.last_discovery = {  # type: ignore[attr-defined]
    "discovered": [],
    "excluded": [],
    "included": [],
    "indexed": [],
    "failed": [],
}


def space_index_doc_count() -> Optional[int]:
    client = get_search_client(space_index_name())
    if not client:
        return None
    try:
        return int(client.get_document_count())
    except Exception as exc:
        logger.warning("Could not read space index doc count: %s", exc)
        return None


def sync_space_to_azure_search(*, embed: bool = True) -> dict[str, Any]:
    """Ensure space index exists and upload docs from all discovered action.* tables."""
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        raise RuntimeError("Azure Search is not configured (AZURE_SEARCH_ENDPOINT / KEY)")

    index = space_index_name()
    if not ensure_index_exists(index):
        raise RuntimeError(f"Failed to create/update Azure Search index {index}")

    docs = load_space_search_docs()
    discovery = getattr(load_space_search_docs, "last_discovery", {}) or {}
    try:
        from app.search.space_module_indexer import load_space_module_search_docs

        module_docs = load_space_module_search_docs()
        docs.extend(module_docs)
        if module_docs:
            discovery.setdefault("indexed", []).append(
                {"table": "cms/dms/incident/chkwp", "docs": len(module_docs), "mode": "module"}
            )
    except Exception:
        logger.warning("Space module indexing skipped", extra={"errorCode": "module_index_failed"})

    if not docs:
        return {
            "index": index,
            "sql_database": SOURCE_DB_NAME,
            "schema": SPACE_SCHEMA,
            "documents_loaded": 0,
            "uploaded_ok": 0,
            "uploaded_failed": 0,
            "discovery": discovery,
            "message": "Space DB returned no indexable rows from discovered action.* tables",
        }

    # Embeddings use title+content (searchable text only) via index_documents
    result = index_documents(docs, embed=embed, index_name=index)
    count = space_index_doc_count()
    indexed_tables = [
        i["table"] for i in discovery.get("indexed", []) if i.get("docs", 0) >= 0
    ]
    return {
        "index": index,
        "sql_database": SOURCE_DB_NAME,
        "schema": SPACE_SCHEMA,
        "tables_discovered": [
            f"{SPACE_SCHEMA}.{t}" for t in discovery.get("discovered", [])
        ],
        "tables_excluded": [
            f"{SPACE_SCHEMA}.{t}" for t in discovery.get("excluded", [])
        ],
        "tables_indexed": indexed_tables,
        "tables_failed": discovery.get("failed", []),
        "per_table": discovery.get("indexed", []),
        "documents_loaded": len(docs),
        "uploaded_ok": result.get("ok", 0),
        "uploaded_failed": result.get("failed", 0),
        "index_doc_count": count,
        "message": (
            f"Synced {result.get('ok', 0)} docs from {SOURCE_DB_NAME}.{SPACE_SCHEMA} "
            f"({len(indexed_tables)} table(s)) into Azure AI Search index '{index}'"
        ),
    }
