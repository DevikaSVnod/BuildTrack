"""
Global Search Core — product SDK for hybrid search + AI answers.

Integrators register connectors (data sources) and extractors (index-time
intelligence). The SearchPipeline orchestrates query → retrieve → answer.

BuildTrack is the reference connector in app/connectors/buildtrack.py.
"""

from global_search_core.models import (
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from global_search_core.connector import SearchConnector, SearchContext
from global_search_core.extractor import ContentExtractor, ExtractionInput, ExtractionResult
from global_search_core.registry import (
    get_connector,
    get_default_connector,
    list_connectors,
    list_extractors,
    register_connector,
    register_extractor,
    set_default_connector,
)
from global_search_core.pipeline import SearchPipeline

__all__ = [
    "SearchConnector",
    "SearchContext",
    "ContentExtractor",
    "ExtractionInput",
    "ExtractionResult",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    "SearchResultItem",
    "SearchPipeline",
    "get_connector",
    "get_default_connector",
    "list_connectors",
    "list_extractors",
    "register_connector",
    "register_extractor",
    "set_default_connector",
]

__version__ = "0.1.0"
