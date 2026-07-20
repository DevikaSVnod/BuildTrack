"""Plugin registry for connectors and extractors."""
from __future__ import annotations

from global_search_core.connector import SearchConnector
from global_search_core.extractor import ContentExtractor

_connectors: dict[str, SearchConnector] = {}
_extractors: dict[str, ContentExtractor] = {}
_default_connector: str | None = None


def register_connector(connector: SearchConnector) -> None:
    _connectors[connector.name] = connector


def register_extractor(extractor: ContentExtractor) -> None:
    _extractors[extractor.name] = extractor


def set_default_connector(name: str) -> None:
    if name not in _connectors:
        raise KeyError(f"Connector not registered: {name}")
    global _default_connector
    _default_connector = name


def get_connector(name: str | None = None) -> SearchConnector:
    key = name or _default_connector
    if not key or key not in _connectors:
        available = ", ".join(sorted(_connectors)) or "(none)"
        raise RuntimeError(
            f"Search connector {key!r} not registered. Available: {available}"
        )
    return _connectors[key]


def get_default_connector() -> SearchConnector | None:
    if not _default_connector:
        return None
    return _connectors.get(_default_connector)


def list_connectors() -> list[str]:
    return sorted(_connectors)


def list_extractors() -> list[str]:
    return sorted(_extractors)


def get_extractors_for(content_type: str) -> list[ContentExtractor]:
    return [e for e in _extractors.values() if e.supports(content_type)]
