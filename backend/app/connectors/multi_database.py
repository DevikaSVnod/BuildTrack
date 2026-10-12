"""
Fan-out connector: search every configured database and merge hits for one answer.

Each source has its own SQL session + Azure Search index. Results are tagged with
database_id / database_label so the answer layer can cite across all of them.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from global_search_core.connector import SearchConnector, SearchContext
from global_search_core.models import SearchHit

from app.connectors.buildtrack import BuildTrackConnector

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="multi-db")


def _merge_by_score(hit_lists: list[list[SearchHit]]) -> list[SearchHit]:
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    merged: list[SearchHit] = []
    for hits in hit_lists:
        for hit in hits:
            hid = str(hit.get("id") or "")
            meta = hit.get("metadata") or {}
            dedupe_key = "|".join(
                [
                    str(hit.get("content_type") or ""),
                    str(hit.get("title") or "").strip().lower(),
                    str(meta.get("database_id") or ""),
                ]
            )
            if hid and hid in seen_ids:
                continue
            if dedupe_key in seen_keys:
                continue
            if hid:
                seen_ids.add(hid)
            seen_keys.add(dedupe_key)
            merged.append(hit)
    merged.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
    return merged


class MultiDatabaseConnector(SearchConnector):
    """Queries all enabled data sources in parallel, then merges results."""

    name = "multi_database"

    def __init__(self) -> None:
        self._inner = BuildTrackConnector()

    def retrieve(
        self,
        *,
        context: SearchContext,
        query: str,
        filter_type: Optional[str],
        top_k: int,
        analysis: Any,
    ) -> list[SearchHit]:
        from app.core.data_sources import select_sources_for_analysis
        from app.search.retrieval import _search_cache, _search_cache_key

        source_ids = context.get("source_ids")
        sources = select_sources_for_analysis(analysis, source_ids)
        if not sources:
            raise RuntimeError("No enabled search data sources configured")

        # Single source: still run Space ProjectId expansion when sibling Space DBs exist.
        if len(sources) == 1:
            hits = self._retrieve_one(
                sources[0], context, query, filter_type, top_k, analysis
            )
            try:
                from app.core.data_sources import get_enabled_sources
                from app.core.space_databases import is_space_source_id
                from app.search.cross_db_links import attach_related_hits
                from app.search.query_intel import parse_manager_filter

                enabled_ids = {s.id for s in get_enabled_sources()}
                space_siblings = {s for s in enabled_ids if is_space_source_id(s)}
                if len(space_siblings) >= 2 and not parse_manager_filter(query):
                    hits = attach_related_hits(
                        hits, query=query, max_related=max(6, top_k)
                    )
                    # Keep room for ProjectId hops beyond the seed top_k rows.
                    hits = hits[: max(top_k * 4, top_k) + 24]
            except Exception as exc:
                logger.warning("Single-source cross-DB attach skipped: %s", exc)
            return hits

        cache_key = _search_cache_key(
            query,
            filter_type,
            top_k,
            analysis.cache_suffix(),
            search_index="multi:" + ",".join(s.id for s in sources),
        )
        if cache_key in _search_cache:
            ts, cached = _search_cache[cache_key]
            if time.time() - ts < 120:
                return cached

        lists: list[list[SearchHit]] = []
        errors: list[str] = []

        def _run(source):
            try:
                return source.id, self._retrieve_one(
                    source, context, query, filter_type, top_k, analysis
                ), None
            except Exception as exc:
                logger.warning("Search failed for data source %s: %s", source.id, exc)
                return source.id, [], str(exc)

        futures = [_executor.submit(_run, s) for s in sources]
        for fut in as_completed(futures):
            sid, hits, err = fut.result()
            lists.append(hits)
            if err:
                errors.append(f"{sid}: {err}")

        merged = _merge_by_score(lists)
        # Cap after merge so answer sees a balanced multi-DB set.
        merged = merged[: max(top_k * 2, top_k)]

        # Soft-link related records across DBs (shared project name today).
        # Skipped for exact person-scoped filters: same-project expansion would
        # add back projects the named manager does not own.
        try:
            from app.search.cross_db_links import attach_related_hits
            from app.search.query_intel import parse_manager_filter

            if not parse_manager_filter(query):
                merged = attach_related_hits(
                    merged, query=query, max_related=max(6, top_k)
                )
                merged = merged[: max(top_k * 4, top_k) + 24]
        except Exception as exc:
            logger.warning("Cross-DB relationship attach skipped: %s", exc)

        _search_cache[cache_key] = (time.time(), merged)
        if errors:
            logger.info(
                "Multi-DB search completed with %s source error(s): %s",
                len(errors),
                "; ".join(errors),
            )
        return merged

    def _retrieve_one(
        self,
        source,
        context: SearchContext,
        query: str,
        filter_type: Optional[str],
        top_k: int,
        analysis: Any,
    ) -> list[SearchHit]:
        from app.core.data_sources import session_for

        db = session_for(source.id)
        try:
            src_ctx = {
                **context,
                "db": db,
                "data_source": source,
            }
            return self._inner.retrieve(
                context=src_ctx,
                query=query,
                filter_type=filter_type,
                top_k=top_k,
                analysis=analysis,
            )
        finally:
            db.close()

    def enrich_cached(
        self,
        *,
        context: SearchContext,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        """Re-enrich cached hits using the database each hit came from."""
        from collections import defaultdict

        from app.core.data_sources import get_source, session_for
        from app.search.document_enrich import enrich_document_results

        if not hits:
            return hits

        by_source: dict[str, list[SearchHit]] = defaultdict(list)
        untagged: list[SearchHit] = []
        for hit in hits:
            meta = hit.get("metadata") or {}
            sid = meta.get("database_id")
            if sid:
                by_source[str(sid)].append(hit)
            else:
                untagged.append(hit)

        enriched: list[SearchHit] = []
        for sid, group in by_source.items():
            source = get_source(sid)
            if source is None:
                enriched.extend(group)
                continue
            if getattr(source, "retrieval_mode", "azure") == "sql":
                for item in group:
                    meta = dict(item.get("metadata") or {})
                    meta["database_id"] = source.id
                    meta["database_label"] = source.label
                    item["metadata"] = meta
                enriched.extend(group)
                continue
            db = session_for(sid)
            try:
                part = enrich_document_results(db, group)
                for item in part:
                    meta = dict(item.get("metadata") or {})
                    meta["database_id"] = source.id
                    meta["database_label"] = source.label
                    item["metadata"] = meta
                enriched.extend(part)
            except Exception as exc:
                logger.warning("enrich_cached failed for %s: %s", sid, exc)
                enriched.extend(group)
            finally:
                db.close()

        # Untagged hits → primary FastAPI session if present.
        if untagged:
            db = context.get("db")
            if db is not None:
                try:
                    enriched.extend(enrich_document_results(db, untagged))
                except Exception:
                    enriched.extend(untagged)
            else:
                enriched.extend(untagged)

        enriched.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
        return enriched
