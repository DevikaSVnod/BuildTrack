"""Catalog routing + document strategy tests."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.search.catalog.loader import sources_for_content_types
from app.search.document_strategy import use_chunk_index_for_query


def test_sources_for_drawing_content_types():
    sources = sources_for_content_types(["drawing"])
    assert "buildtrack" in sources


def test_sources_for_material_content_types():
    sources = sources_for_content_types(["material", "materials"])
    assert "assets" in sources


def test_chunk_strategy_for_document_query():
    # Force flag on for test
    prev = settings.SEARCH_CHUNK_INDEX_FOR_DOCS
    try:
        settings.SEARCH_CHUNK_INDEX_FOR_DOCS = True
        assert use_chunk_index_for_query(
            "What payment conditions are in the contract document?"
        )
    finally:
        settings.SEARCH_CHUNK_INDEX_FOR_DOCS = prev


def test_select_sources_uses_catalog(monkeypatch=None):
    from app.core import data_sources as ds

    ds.list_configured_sources.cache_clear()
    analysis = SimpleNamespace(content_types=["drawing"])
    prev = settings.SEARCH_CATALOG_ENABLED
    try:
        settings.SEARCH_CATALOG_ENABLED = True
        selected = ds.select_sources_for_analysis(analysis)
        ids = {s.id for s in selected}
        # Drawing maps to buildtrack; should not require every source
        assert "buildtrack" in ids
    finally:
        settings.SEARCH_CATALOG_ENABLED = prev
