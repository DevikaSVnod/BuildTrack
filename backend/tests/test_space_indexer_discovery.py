"""Unit tests for Space Action table discovery helpers (no live DB required)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.search.space_indexer import (
    EXCLUDED_TABLES,
    SPECIAL_TABLES,
    _content_type_for_table,
    _pick_title_column,
    _safe_ident,
    _searchable_columns,
)


def test_excluded_tables():
    assert "OfflineSyncLog" in EXCLUDED_TABLES
    assert "Synonyms_Configuration" in EXCLUDED_TABLES
    assert "Events" not in EXCLUDED_TABLES


def test_special_tables_preserved():
    assert SPECIAL_TABLES == {"Events", "Event_Agenda", "Event_Information"}


def test_content_type_mapping():
    assert _content_type_for_table("Events") == "event"
    assert _content_type_for_table("Event_Task") == "event_task"
    assert _content_type_for_table("Task_ReviewProcess") == "task_reviewprocess"


def test_safe_ident_rejects_injection():
    try:
        _safe_ident("Events; DROP TABLE")
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert _safe_ident("Event_Task") == "Event_Task"


def test_searchable_columns_text_only():
    columns = [
        {"COLUMN_NAME": "EventTaskId", "DATA_TYPE": "int", "CHARACTER_MAXIMUM_LENGTH": None},
        {"COLUMN_NAME": "Title", "DATA_TYPE": "nvarchar", "CHARACTER_MAXIMUM_LENGTH": 200},
        {"COLUMN_NAME": "Payload", "DATA_TYPE": "varbinary", "CHARACTER_MAXIMUM_LENGTH": None},
        {"COLUMN_NAME": "Notes", "DATA_TYPE": "nvarchar", "CHARACTER_MAXIMUM_LENGTH": -1},
    ]
    searchable = _searchable_columns(columns, ["EventTaskId"])
    assert "Title" in searchable
    assert "Notes" in searchable
    assert "Payload" not in searchable
    assert "EventTaskId" not in searchable


def test_pick_title_prefers_title():
    columns = [
        {"COLUMN_NAME": "Id", "DATA_TYPE": "int", "CHARACTER_MAXIMUM_LENGTH": None},
        {"COLUMN_NAME": "Title", "DATA_TYPE": "nvarchar", "CHARACTER_MAXIMUM_LENGTH": 100},
        {"COLUMN_NAME": "Description", "DATA_TYPE": "nvarchar", "CHARACTER_MAXIMUM_LENGTH": 500},
    ]
    assert _pick_title_column(columns, ["Id"]) == "Title"
