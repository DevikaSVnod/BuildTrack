from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    max_length: Optional[int] = None
    is_nullable: bool = True
    is_primary_key: bool = False
    description: str = ""


@dataclass
class TableInfo:
    schema_name: str
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""
    search_hints: list[str] = field(default_factory=list)


@dataclass
class DatabaseSnapshot:
    source_id: str
    source_label: str
    database_name: str
    schema_name: str
    version: int
    captured_at: str
    tables: list[TableInfo] = field(default_factory=list)
    change_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DatabaseSnapshot":
        tables: list[TableInfo] = []
        for t in raw.get("tables") or []:
            cols = [
                ColumnInfo(
                    name=c.get("name") or "",
                    data_type=c.get("data_type") or "",
                    max_length=c.get("max_length"),
                    is_nullable=bool(c.get("is_nullable", True)),
                    is_primary_key=bool(c.get("is_primary_key", False)),
                    description=c.get("description") or "",
                )
                for c in (t.get("columns") or [])
            ]
            tables.append(
                TableInfo(
                    schema_name=t.get("schema_name") or "",
                    name=t.get("name") or "",
                    columns=cols,
                    primary_keys=list(t.get("primary_keys") or []),
                    foreign_keys=list(t.get("foreign_keys") or []),
                    description=t.get("description") or "",
                    search_hints=list(t.get("search_hints") or []),
                )
            )
        return cls(
            source_id=raw.get("source_id") or "",
            source_label=raw.get("source_label") or "",
            database_name=raw.get("database_name") or "",
            schema_name=raw.get("schema_name") or "",
            version=int(raw.get("version") or 1),
            captured_at=raw.get("captured_at") or "",
            tables=tables,
            change_summary=list(raw.get("change_summary") or []),
        )


def table_fingerprint(table: TableInfo) -> dict[str, str]:
    """Column name → type map for change detection."""
    return {c.name: c.data_type for c in table.columns}
