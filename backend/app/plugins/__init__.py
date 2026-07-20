"""Register Global Search product plugins for this host application."""
from __future__ import annotations

from global_search_core.registry import register_connector, register_extractor, set_default_connector

from app.connectors.buildtrack import BuildTrackConnector
from app.extractors.buildtrack import DocumentBodyTextExtractor, DrawingIntelligenceExtractor

_registered = False


def register_all_plugins() -> None:
    global _registered
    if _registered:
        return
    register_connector(BuildTrackConnector())
    register_extractor(DrawingIntelligenceExtractor())
    register_extractor(DocumentBodyTextExtractor())
    set_default_connector("buildtrack")
    _registered = True
