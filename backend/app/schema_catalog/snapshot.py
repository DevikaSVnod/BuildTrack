"""Introspect Space SQL schema(s) and persist versioned snapshots."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text

from app.core.space_databases import (
    SpaceDbConfig,
    get_space_db_config,
    list_space_db_configs,
    resolve_space_database_url,
)
from app.schema_catalog.descriptions import describe_column, describe_table
from app.schema_catalog.models import (
    ColumnInfo,
    DatabaseSnapshot,
    TableInfo,
    table_fingerprint,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "schema_catalog"
_CURRENT = "current.json"
_PREVIOUS = "previous.json"
_OLDER = "older.json"
_HISTORY = "change_history.json"


def _catalog_dir() -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed reading schema snapshot %s: %s", path, exc)
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_current_snapshot(source_id: str = "space") -> Optional[DatabaseSnapshot]:
    raw = _read_json(_catalog_dir() / f"{source_id}_{_CURRENT}")
    if not raw and source_id == "space":
        # fallback legacy name
        raw = _read_json(_catalog_dir() / _CURRENT)
    if not raw:
        return None
    return DatabaseSnapshot.from_dict(raw)


def list_current_snapshots() -> list[DatabaseSnapshot]:
    snaps: list[DatabaseSnapshot] = []
    for cfg in list_space_db_configs(enabled_only=False):
        snap = load_current_snapshot(cfg.source_id)
        if snap is not None:
            snaps.append(snap)
    return snaps


def _diff_snapshots(
    old: Optional[DatabaseSnapshot], new: DatabaseSnapshot
) -> list[str]:
    if old is None:
        return [f"Initial snapshot v{new.version} with {len(new.tables)} tables"]
    changes: list[str] = []
    old_map = {t.name: t for t in old.tables}
    new_map = {t.name: t for t in new.tables}
    for name in sorted(set(new_map) - set(old_map)):
        changes.append(f"Added table: {name}")
    for name in sorted(set(old_map) - set(new_map)):
        changes.append(f"Removed table: {name}")
    for name in sorted(set(old_map) & set(new_map)):
        old_fp = table_fingerprint(old_map[name])
        new_fp = table_fingerprint(new_map[name])
        for col in sorted(set(new_fp) - set(old_fp)):
            changes.append(f"Added: {name}.{col}")
        for col in sorted(set(old_fp) - set(new_fp)):
            changes.append(f"Removed: {name}.{col}")
        for col in sorted(set(old_fp) & set(new_fp)):
            if old_fp[col] != new_fp[col]:
                changes.append(
                    f"Changed: {name}.{col} datatype {old_fp[col]} -> {new_fp[col]}"
                )
    return changes


def _append_history(source_id: str, version: int, changes: list[str]) -> None:
    path = _catalog_dir() / f"{source_id}_{_HISTORY}"
    history = _read_json(path) or {"entries": []}
    entries = list(history.get("entries") or [])
    entries.insert(
        0,
        {
            "version": version,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "changes": changes,
        },
    )
    history["entries"] = entries[:50]
    _write_json(path, history)


def _rotate_and_save(source_id: str, snap: DatabaseSnapshot) -> None:
    d = _catalog_dir()
    cur_path = d / f"{source_id}_{_CURRENT}"
    prev_path = d / f"{source_id}_{_PREVIOUS}"
    older_path = d / f"{source_id}_{_OLDER}"
    if prev_path.exists():
        older_path.write_text(prev_path.read_text(encoding="utf-8"), encoding="utf-8")
    if cur_path.exists():
        prev_path.write_text(cur_path.read_text(encoding="utf-8"), encoding="utf-8")
    _write_json(cur_path, snap.to_dict())


def _engine_for(cfg: SpaceDbConfig):
    from scripts.setup_assets_db import create_mssql_engine

    return create_mssql_engine(resolve_space_database_url(cfg))


def introspect_space_schema(cfg: Optional[SpaceDbConfig] = None) -> DatabaseSnapshot:
    """Read INFORMATION_SCHEMA from a Space SQL database."""
    if cfg is None:
        cfg = get_space_db_config("space")
        if cfg is None:
            raise RuntimeError("Space Action config missing")

    engine = _engine_for(cfg)
    schema = cfg.schema_name
    tables: list[TableInfo] = []
    try:
        with engine.connect() as conn:
            table_rows = conn.execute(
                text(
                    """
                    SELECT TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                    """
                ),
                {"schema": schema},
            ).fetchall()

            pk_rows = conn.execute(
                text(
                    """
                    SELECT ku.TABLE_NAME, ku.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                      ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                     AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
                    WHERE tc.TABLE_SCHEMA = :schema
                      AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    """
                ),
                {"schema": schema},
            ).fetchall()
            pk_map: dict[str, list[str]] = {}
            for tname, cname in pk_rows:
                pk_map.setdefault(str(tname), []).append(str(cname))

            try:
                fk_rows = conn.execute(
                    text(
                        """
                        SELECT
                          fk.TABLE_NAME AS from_table,
                          cu.COLUMN_NAME AS from_column,
                          pk.TABLE_NAME AS to_table,
                          pt.COLUMN_NAME AS to_column
                        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                        JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS fk
                          ON rc.CONSTRAINT_NAME = fk.CONSTRAINT_NAME
                         AND rc.CONSTRAINT_SCHEMA = fk.TABLE_SCHEMA
                        JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk
                          ON rc.UNIQUE_CONSTRAINT_NAME = pk.CONSTRAINT_NAME
                         AND rc.UNIQUE_CONSTRAINT_SCHEMA = pk.TABLE_SCHEMA
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE cu
                          ON rc.CONSTRAINT_NAME = cu.CONSTRAINT_NAME
                         AND rc.CONSTRAINT_SCHEMA = cu.TABLE_SCHEMA
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE pt
                          ON rc.UNIQUE_CONSTRAINT_NAME = pt.CONSTRAINT_NAME
                         AND rc.UNIQUE_CONSTRAINT_SCHEMA = pt.TABLE_SCHEMA
                         AND cu.ORDINAL_POSITION = pt.ORDINAL_POSITION
                        WHERE fk.TABLE_SCHEMA = :schema
                        """
                    ),
                    {"schema": schema},
                ).fetchall()
            except Exception as exc:
                logger.warning("FK introspection skipped (%s): %s", cfg.source_id, exc)
                fk_rows = []
            fk_map: dict[str, list[dict[str, Any]]] = {}
            for from_t, from_c, to_t, to_c in fk_rows:
                fk_map.setdefault(str(from_t), []).append(
                    {
                        "from_column": str(from_c),
                        "to_table": str(to_t),
                        "to_column": str(to_c),
                    }
                )

            for (table_name,) in table_rows:
                tname = str(table_name)
                if tname in cfg.excluded_tables:
                    continue
                col_rows = conn.execute(
                    text(
                        """
                        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                               IS_NULLABLE
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
                        ORDER BY ORDINAL_POSITION
                        """
                    ),
                    {"schema": schema, "table": tname},
                ).fetchall()
                pks = pk_map.get(tname) or []
                cols: list[ColumnInfo] = []
                for cname, dtype, maxlen, nullable in col_rows:
                    cols.append(
                        ColumnInfo(
                            name=str(cname),
                            data_type=str(dtype),
                            max_length=int(maxlen) if maxlen is not None else None,
                            is_nullable=str(nullable).upper() == "YES",
                            is_primary_key=str(cname) in pks,
                            description=describe_column(
                                tname, str(cname), str(dtype)
                            ),
                        )
                    )
                desc, hints = describe_table(tname, source_label=cfg.label)
                tables.append(
                    TableInfo(
                        schema_name=schema,
                        name=tname,
                        columns=cols,
                        primary_keys=pks,
                        foreign_keys=fk_map.get(tname) or [],
                        description=desc,
                        search_hints=hints,
                    )
                )
    finally:
        engine.dispose()

    return DatabaseSnapshot(
        source_id=cfg.source_id,
        source_label=cfg.label,
        database_name=cfg.database_name,
        schema_name=schema,
        version=1,
        captured_at=datetime.now(timezone.utc).isoformat(),
        tables=tables,
    )


def refresh_one_schema_catalog(cfg: SpaceDbConfig) -> dict[str, Any]:
    """Introspect one Space DB, diff vs current snapshot, rotate versions, save."""
    fresh = introspect_space_schema(cfg)
    previous = load_current_snapshot(cfg.source_id)
    next_version = (previous.version + 1) if previous else 1
    changes = _diff_snapshots(previous, fresh)
    fresh.version = next_version
    fresh.change_summary = changes
    if previous is not None and not any(
        c.startswith("Added") or c.startswith("Removed") or c.startswith("Changed")
        for c in changes
    ):
        fresh.version = previous.version
        fresh.change_summary = ["No schema structure change"]
        _write_json(
            _catalog_dir() / f"{cfg.source_id}_{_CURRENT}",
            fresh.to_dict(),
        )
        return {
            "source_id": cfg.source_id,
            "database_name": cfg.database_name,
            "version": fresh.version,
            "tables": len(fresh.tables),
            "changed": False,
            "changes": fresh.change_summary,
        }

    _rotate_and_save(cfg.source_id, fresh)
    _append_history(cfg.source_id, fresh.version, changes)
    return {
        "source_id": cfg.source_id,
        "database_name": cfg.database_name,
        "version": fresh.version,
        "tables": len(fresh.tables),
        "changed": True,
        "changes": changes,
    }


def refresh_space_schema_catalog(
    source_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Refresh schema catalog for one Space DB (source_id) or all enabled Space DBs.
    """
    if source_id:
        cfg = get_space_db_config(source_id)
        if cfg is None:
            raise RuntimeError(f"Unknown Space source_id: {source_id}")
        return refresh_one_schema_catalog(cfg)

    configs = list_space_db_configs(enabled_only=True)
    if not configs:
        raise RuntimeError("No enabled Space databases configured")

    results = [refresh_one_schema_catalog(cfg) for cfg in configs]
    return {
        "sources": results,
        "source_count": len(results),
        "tables": sum(int(r.get("tables") or 0) for r in results),
        "changed": any(bool(r.get("changed")) for r in results),
    }
