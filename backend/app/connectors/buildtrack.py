"""BuildTrack reference connector — Azure Search + SQL enrich for one data source."""
from __future__ import annotations

from typing import Any, Optional

from global_search_core.connector import SearchConnector, SearchContext
from global_search_core.models import SearchHit


def _tag_hits_with_source(hits: list[SearchHit], source: Any) -> list[SearchHit]:
    if source is None:
        return hits
    tagged: list[SearchHit] = []
    for hit in hits:
        item = dict(hit)
        meta = dict(item.get("metadata") or {})
        meta["database_id"] = source.id
        meta["database_label"] = source.label
        item["metadata"] = meta
        # Prefix id so hits from different DBs never collide in the UI/cache.
        raw_id = str(item.get("id") or "")
        prefix = f"{source.id}::"
        if raw_id and not raw_id.startswith(prefix):
            item["id"] = f"{prefix}{raw_id}"
        tagged.append(item)
    return tagged


class BuildTrackConnector(SearchConnector):
    """Single-database BuildTrack retrieval (used alone or by MultiDatabaseConnector)."""

    name = "buildtrack"

    def retrieve(
        self,
        *,
        context: SearchContext,
        query: str,
        filter_type: Optional[str],
        top_k: int,
        analysis: Any,
    ) -> list[SearchHit]:
        db = context.get("db")
        if db is None:
            raise RuntimeError("BuildTrackConnector requires context['db'] (SQLAlchemy session)")

        source = context.get("data_source")
        mode = getattr(source, "retrieval_mode", "azure") if source else "azure"

        # Second / satellite DBs can use a local search_documents table (no Azure index).
        if mode == "sql" or (source and not getattr(source, "search_index", None)):
            from app.search.sql_source_search import sql_search_documents

            raw = sql_search_documents(
                db,
                query,
                filter_type=filter_type,
                top_k=top_k,
            )
            return _tag_hits_with_source(raw, source)

        from app.search.retrieval import hybrid_search
        from app.search.document_enrich import enrich_document_results

        search_index = getattr(source, "search_index", None) if source else None
        raw = hybrid_search(
            query=query,
            filter_type=filter_type,
            top_k=top_k,
            analysis=analysis,
            search_index=search_index,
        )
        # Satellite DBs (e.g. assets SQLite) do not share BuildTrack ORM tables —
        # Azure hits are already complete; skip SQL enrich against the wrong schema.
        if source and getattr(source, "id", None) == "assets":
            return _tag_hits_with_source(raw, source)

        from app.search.document_enrich import enrich_document_results

        enriched = enrich_document_results(db, raw)
        return _tag_hits_with_source(enriched, source)

    def enrich_cached(
        self,
        *,
        context: SearchContext,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        source = context.get("data_source")
        mode = getattr(source, "retrieval_mode", None) if source else None
        # SQL-sourced hits are already complete; skip BuildTrack SQL enrich.
        if mode == "sql":
            return _tag_hits_with_source(hits, source)

        # Multi-DB enrich path may group by database_id — leave as-is if no db.
        from app.search.document_enrich import enrich_document_results

        db = context.get("db")
        if db is None:
            return hits
        enriched = enrich_document_results(db, hits)
        return _tag_hits_with_source(enriched, source)
