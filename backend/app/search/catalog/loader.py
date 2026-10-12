"""Load and cache YAML entity catalog definitions."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.search.catalog.models import EntityCatalog, RelationshipRef

logger = logging.getLogger(__name__)

_ENTITIES_DIR = Path(__file__).resolve().parent / "entities"


def _parse_entity(raw: dict) -> EntityCatalog:
    rels = tuple(
        RelationshipRef(field=str(r["field"]), ref=str(r["ref"]))
        for r in (raw.get("relationships") or [])
        if isinstance(r, dict) and r.get("field") and r.get("ref")
    )
    return EntityCatalog(
        entity=str(raw["entity"]),
        source=str(raw["source"]),
        table=str(raw["table"]),
        id_field=str(raw.get("id_field") or "id"),
        entity_type=str(raw.get("entity_type") or raw["entity"]),
        search_fields=tuple(raw.get("search_fields") or ()),
        filter_fields=tuple(raw.get("filter_fields") or ()),
        sortable_fields=tuple(raw.get("sortable_fields") or ()),
        embedding_enabled=bool(raw.get("embedding_enabled", True)),
        sql_only_fields=tuple(raw.get("sql_only_fields") or ()),
        acl_fields=tuple(raw.get("acl_fields") or ()),
        hydrate_fields=tuple(raw.get("hydrate_fields") or ()),
        relationships=rels,
        updated_at_field=raw.get("updated_at_field"),
        title_field=raw.get("title_field"),
        url_template=raw.get("url_template"),
        domain_signals=tuple(raw.get("domain_signals") or ()),
        description=str(raw.get("description") or ""),
        index_body_text=bool(raw.get("index_body_text", False)),
    )


@lru_cache(maxsize=1)
def get_catalog() -> dict[str, EntityCatalog]:
    """Return entity_name → EntityCatalog."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for the schema catalog") from exc

    catalog: dict[str, EntityCatalog] = {}
    if not _ENTITIES_DIR.is_dir():
        logger.warning("Catalog entities directory missing: %s", _ENTITIES_DIR)
        return catalog

    for path in sorted(_ENTITIES_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            entity = _parse_entity(raw)
            catalog[entity.entity] = entity
        except Exception as exc:
            logger.error("Failed to load catalog entity %s: %s", path.name, exc)
    logger.info("Loaded schema catalog: %s entities", len(catalog))
    return catalog


def list_entities(source: Optional[str] = None) -> list[EntityCatalog]:
    items = list(get_catalog().values())
    if source:
        items = [e for e in items if e.source == source]
    return items


def get_entity(entity: str) -> Optional[EntityCatalog]:
    return get_catalog().get(entity)


def get_entity_by_type(entity_type: str) -> Optional[EntityCatalog]:
    for ent in get_catalog().values():
        if ent.entity_type == entity_type:
            return ent
    return None


def sources_for_content_types(content_types: list[str]) -> list[str]:
    """Map detected content_types / signals to catalog source ids."""
    if not content_types:
        return []
    wanted = {c.lower() for c in content_types}
    sources: list[str] = []
    for ent in get_catalog().values():
        signals = {ent.entity_type, ent.entity, *ent.domain_signals}
        signals_l = {s.lower() for s in signals}
        if wanted & signals_l:
            if ent.source not in sources:
                sources.append(ent.source)
    return sources


def reload_catalog() -> dict[str, EntityCatalog]:
    get_catalog.cache_clear()
    return get_catalog()
