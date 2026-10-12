"""Schema catalog — configuration-driven indexing, routing, and hydration."""
from app.search.catalog.loader import get_catalog, get_entity, list_entities
from app.search.catalog.models import EntityCatalog, FieldTier

__all__ = [
    "EntityCatalog",
    "FieldTier",
    "get_catalog",
    "get_entity",
    "list_entities",
]
