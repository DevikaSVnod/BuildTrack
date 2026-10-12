"""
Inventory of POC content_types and index fields vs production discovery model.

SQL / API = source of truth.
Azure AI Search = slim discovery layer (ids + Tier1/Tier2 + optional vector).
"""
from __future__ import annotations

from typing import Any

# content_type values produced by vw_global_search_documents + satellite indexes
POC_CONTENT_TYPES: tuple[str, ...] = (
    "project",
    "task",
    "document",
    "team",
    "handover",
    "drawing",
    "safety",
    "attendance",
    "timeline",
    "report",
    "equipment",
    "vendor",
    "material",
    "event",
    "event_agenda",
    "event_information",
)

# Fields on the legacy Azure AI Search index (ensure_index_exists)
LEGACY_INDEX_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "content",
    "content_type",
    "url",
    "metadata",
    "progress_pct",
    "record_status",
    "content_vector",
)

# Production discovery fields (added alongside legacy for compatibility)
DISCOVERY_INDEX_FIELDS: tuple[str, ...] = (
    "entity_id",
    "entity_type",
    "source_database",
    "search_text",
    "search_text_hash",
    "updated_at",
    "project_id",
    "organization_id",
    "tenant_id",
    "access_groups",
    "location",
    "status",
)


def inventory_snapshot() -> dict[str, Any]:
    from app.search.catalog.loader import list_entities

    return {
        "principle": "DB/API is source of truth; Azure AI Search is discovery only",
        "poc_content_types": list(POC_CONTENT_TYPES),
        "legacy_index_fields": list(LEGACY_INDEX_FIELDS),
        "discovery_index_fields": list(DISCOVERY_INDEX_FIELDS),
        "catalog_entities": [e.to_public_dict() for e in list_entities()],
    }
