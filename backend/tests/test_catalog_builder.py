"""Unit tests for schema catalog + canonical search document builder."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.search.catalog.builder import (
    build_canonical_document,
    build_search_text,
    search_text_hash,
)
from app.search.catalog.loader import get_entity, list_entities, reload_catalog
from app.search.catalog.models import FieldTier


def test_catalog_loads_core_entities():
    reload_catalog()
    names = {e.entity for e in list_entities()}
    assert {"project", "task", "document", "drawing", "material"}.issubset(names)


def test_project_tiers():
    ent = get_entity("project")
    assert ent is not None
    assert ent.tier_for("name") == FieldTier.SEARCH
    assert ent.tier_for("status") == FieldTier.FILTER
    assert ent.tier_for("budget") == FieldTier.SQL_ONLY


def test_canonical_project_excludes_sql_only_from_search_text():
    reload_catalog()
    row = SimpleNamespace(
        id=1001,
        name="Mumbai Electrical Upgrade",
        description="Electrical upgrade for commercial building",
        location="Mumbai",
        status=SimpleNamespace(value="Delayed"),
        progress=40,
        budget=999999.0,
        start_date=None,
        end_date=None,
        project_manager_id=1,
        created_at=None,
        project_manager=None,
    )
    doc = build_canonical_document("project", row)
    assert doc is not None
    assert doc["entity_id"] == "1001"
    assert doc["entity_type"] == "project"
    assert doc["source_database"] == "buildtrack"
    assert "Mumbai Electrical Upgrade" in doc["search_text"]
    assert "999999" not in doc["search_text"]  # budget is sql_only
    assert doc["search_text_hash"] == search_text_hash(doc["search_text"])
    assert doc["project_id"] == "1001"
    assert doc.get("status") == "Delayed"


def test_hash_stable_for_same_text():
    a = search_text_hash("hello world")
    b = search_text_hash("hello world")
    c = search_text_hash("hello world!")
    assert a == b
    assert a != c


def test_document_body_not_in_discovery_text():
    reload_catalog()
    row = {
        "id": 7,
        "name": "Contract.pdf",
        "file_type": "PDF",
        "body_text": "SECRET PAYMENT CLAUSE SHOULD NOT BE INDEXED HERE",
        "project_id": 1,
        "uploaded_by": 1,
        "file_size": 100,
        "file_url": "https://example/blob",
        "created_at": None,
    }
    doc = build_canonical_document("document", row)
    assert doc is not None
    assert "SECRET PAYMENT" not in (doc.get("search_text") or "")
    assert "SECRET PAYMENT" not in (doc.get("content") or "")
