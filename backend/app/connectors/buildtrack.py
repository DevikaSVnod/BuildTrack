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
        if not meta.get("database_id"):
            meta["database_id"] = source.id
        if not meta.get("database_label"):
            meta["database_label"] = source.label
        item["metadata"] = meta
        # Prefix id so hits from different DBs never collide in the UI/cache.
        raw_id = str(item.get("id") or "")
        prefix = f"{source.id}::"
        if raw_id and not raw_id.startswith(prefix) and not str(raw_id).startswith("cross-db-"):
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
        source_id = getattr(source, "id", None) if source else None

        # Space DBs: schema-SQL hybrid (optional Azure row index for Action only).
        from app.core.space_databases import is_space_source_id

        if is_space_source_id(source_id):
            from app.search.space_hybrid import retrieve_space_hybrid

            data_hits: list[SearchHit] = []
            search_index = getattr(source, "search_index", None) if source else None
            if search_index and mode == "azure":
                from app.search.retrieval import hybrid_search

                data_hits = hybrid_search(
                    query=query,
                    filter_type=filter_type,
                    top_k=top_k,
                    analysis=analysis,
                    search_index=search_index,
                    security_filter=None,
                )
            merged = retrieve_space_hybrid(
                query=query,
                filter_type=filter_type,
                top_k=top_k,
                analysis=analysis,
                data_index_hits=data_hits,
                source_id=str(source_id),
            )
            return _tag_hits_with_source(merged, source)

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
        from app.core.config import settings

        search_index = getattr(source, "search_index", None) if source else None
        security_filter = None
        if settings.SEARCH_SECURITY_TRIMMING and context.get("user") is not None:
            from app.search.security_trim import build_security_odata

            security_filter = build_security_odata(context.get("user"), db)

        raw = hybrid_search(
            query=query,
            filter_type=filter_type,
            top_k=top_k,
            analysis=analysis,
            search_index=search_index,
            security_filter=security_filter,
        )
        # Satellite DBs skip BuildTrack ORM enrich, but still resolve crawl
        # sidecar titles to the real uploaded PDF/DOCX via the shared index.
        if source_id == "assets":
            from app.search.blob_retrieval import _resolve_sidecar_titles

            return _tag_hits_with_source(_resolve_sidecar_titles(raw), source)

        from app.search.document_enrich import enrich_document_results

        enriched = enrich_document_results(db, raw)
        if settings.SEARCH_HYDRATE_FROM_SQL:
            from app.search.hydrate import enrich_hits_from_sql

            enriched = enrich_hits_from_sql(
                enriched, context=context, user=context.get("user")
            )
        return _tag_hits_with_source(enriched, source)

    def enrich_cached(
        self,
        *,
        context: SearchContext,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        source = context.get("data_source")
        mode = getattr(source, "retrieval_mode", None) if source else None
        source_id = getattr(source, "id", None) if source else None
        # SQL / Space hits are already complete; skip BuildTrack SQL enrich.
        from app.core.space_databases import is_space_source_id

        if mode == "sql" or is_space_source_id(source_id):
            return _tag_hits_with_source(hits, source)

        # Multi-DB enrich path may group by database_id — leave as-is if no db.
        from app.search.document_enrich import enrich_document_results

        db = context.get("db")
        if db is None:
            return hits
        enriched = enrich_document_results(db, hits)
        return _tag_hits_with_source(enriched, source)
