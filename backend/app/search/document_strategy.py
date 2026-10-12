"""
Formal split: structured entity discovery vs document chunk (RAG) search.

Structured documents in the entity index store metadata + pointer only.
Clause/passage search uses the blob/RAG chunk index.
"""
from __future__ import annotations

from app.core.config import settings
from app.search.query_intel import is_document_content_query, is_file_content_query


def use_chunk_index_for_query(query: str) -> bool:
    """True when the query should hit blob/RAG chunks rather than fat body text."""
    if not settings.SEARCH_CHUNK_INDEX_FOR_DOCS:
        return False
    return is_document_content_query(query) or is_file_content_query(query)


def entity_index_includes_body() -> bool:
    """Discovery entity index should not store full document body when chunk strategy is on."""
    return not settings.SEARCH_CHUNK_INDEX_FOR_DOCS


def document_discovery_fields() -> tuple[str, ...]:
    return ("name", "file_type", "project_id", "uploader", "upload_date", "file_size")
