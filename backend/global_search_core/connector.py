"""Search connector plugin interface — one implementation per customer data source."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from global_search_core.models import SearchHit

# Opaque bag passed from host app (db session, user, tenant id, etc.)
SearchContext = dict[str, Any]


class SearchConnector(ABC):
    """
    Retrieves and enriches search hits for a tenant's content sources.

    Implementations wrap Azure Search, SQL, SharePoint, S3, etc.
    """

    name: str = "base"

    @abstractmethod
    def retrieve(
        self,
        *,
        context: SearchContext,
        query: str,
        filter_type: Optional[str],
        top_k: int,
        analysis: Any,
    ) -> list[SearchHit]:
        """Return raw search hits (dicts with id, title, snippet, content_type, url, metadata, score)."""

    def enrich_cached(
        self,
        *,
        context: SearchContext,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        """Optional second pass when reusing cached hits (e.g. attach SQL metadata)."""
        return hits
