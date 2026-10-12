"""Typed schema catalog models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FieldTier(str, Enum):
    SEARCH = "search"  # Tier 1 — keyword (+ optional vector via search_text)
    FILTER = "filter"  # Tier 2 — structured filters, no dedicated embedding
    SQL_ONLY = "sql_only"  # Tier 3 — never indexed


@dataclass(frozen=True)
class RelationshipRef:
    field: str
    ref: str


@dataclass(frozen=True)
class EntityCatalog:
    entity: str
    source: str
    table: str
    id_field: str
    entity_type: str
    search_fields: tuple[str, ...] = ()
    filter_fields: tuple[str, ...] = ()
    sortable_fields: tuple[str, ...] = ()
    embedding_enabled: bool = True
    sql_only_fields: tuple[str, ...] = ()
    acl_fields: tuple[str, ...] = ()
    hydrate_fields: tuple[str, ...] = ()
    relationships: tuple[RelationshipRef, ...] = ()
    updated_at_field: Optional[str] = None
    title_field: Optional[str] = None
    url_template: Optional[str] = None
    domain_signals: tuple[str, ...] = ()
    description: str = ""
    index_body_text: bool = False  # documents: keep body out of entity index when False

    def tier_for(self, column: str) -> FieldTier:
        if column in self.search_fields:
            return FieldTier.SEARCH
        if column in self.filter_fields or column in self.acl_fields:
            return FieldTier.FILTER
        if column in self.sql_only_fields:
            return FieldTier.SQL_ONLY
        return FieldTier.SQL_ONLY

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "source": self.source,
            "table": self.table,
            "id_field": self.id_field,
            "entity_type": self.entity_type,
            "search_fields": list(self.search_fields),
            "filter_fields": list(self.filter_fields),
            "sortable_fields": list(self.sortable_fields),
            "embedding_enabled": self.embedding_enabled,
            "sql_only_fields": list(self.sql_only_fields),
            "acl_fields": list(self.acl_fields),
            "hydrate_fields": list(self.hydrate_fields),
            "updated_at_field": self.updated_at_field,
            "domain_signals": list(self.domain_signals),
            "description": self.description,
            "index_body_text": self.index_body_text,
        }
