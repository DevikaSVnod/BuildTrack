"""SPACE module-API search (Phase 1) — no SQL, no Azure, no page URLs."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.search.space_module_search import (
    cms_document_matches_query,
    extract_space_search_terms,
    looks_like_checklist_browse,
    looks_like_contract_browse,
    looks_like_document_browse,
    looks_like_event_number,
    looks_like_incident_browse,
    looks_like_meeting_browse,
    map_cms_item,
    map_event_request_info,
    map_meeting_item,
    space_module_search,
    _envelope_items,
)
from app.search.space_auth import hash_user_id
from global_search_core.models import SearchRequest, SearchResultItem


@pytest.fixture(autouse=True)
def _no_live_azure_and_no_cache(monkeypatch):
    """Unit tests must not call Azure or reuse a previous search response."""
    monkeypatch.setattr("app.search.space_module_search.discover_space_docs", lambda *a, **k: [])
    monkeypatch.setattr("app.search.space_module_search.is_azure_discovery_enabled", lambda: False)
    from app.search.space_module_search import _SPACE_RESULT_CACHE

    _SPACE_RESULT_CACHE.clear()
    yield
    _SPACE_RESULT_CACHE.clear()


def test_event_number_detection():
    assert looks_like_event_number("EVT-12") is True
    assert looks_like_event_number("1042") is True
    assert looks_like_event_number("tower crane") is False


def test_browse_keywords():
    assert looks_like_meeting_browse("events") is True
    assert looks_like_meeting_browse("Meetings") is True
    assert looks_like_meeting_browse("crane") is False
    assert looks_like_contract_browse("contracts") is True
    assert looks_like_contract_browse("cms") is True
    assert looks_like_contract_browse("highway") is False
    assert looks_like_document_browse("documents") is True
    assert looks_like_incident_browse("incidents") is True
    assert looks_like_checklist_browse("checklists") is True
    assert extract_space_search_terms("what meetings mention crane?") == "crane"
    assert cms_document_matches_query(
        {"projectName": "P_AHMPR - Ahmedabad", "regionName": "Ahmedabad"},
        "what contracts mention Ahmedabad?",
    )


def test_meeting_map_has_identity_and_empty_url():
    item = map_meeting_item(
        {
            "eventId": 42,
            "eventNumber": "EVT-0042",
            "topic": "Tower crane inspection",
            "categoryName": "Safety",
        },
        "crane",
    )
    assert item is not None
    assert item.url == ""
    assert item.content_type == "meeting"
    assert item.metadata["source"] == "action"
    assert item.metadata["entityType"] == "meeting"
    assert item.metadata["entityId"] == "42"
    assert "crane" in item.title.lower()


def test_cms_map_requires_both_ids_and_keeps_empty_url():
    assert map_cms_item({"projectCMId": 88, "projectName": "Highway"}, "highway") is None
    item = map_cms_item(
        {
            "projectId": 10,
            "projectCMId": 88,
            "projectName": "Coastal Highway Package A",
            "regionName": "West",
        },
        "highway",
    )
    assert item is not None
    assert item.url == ""
    assert item.metadata["projectId"] == 10
    assert item.metadata["entityId"] == "88"


def test_cms_query_match_uses_real_fields_only():
    row = {"projectName": "P_AHMPR - Ahmedabad", "regionName": "Ahmedabad"}
    assert cms_document_matches_query(row, "Ahmedabad") is True
    assert cms_document_matches_query(row, "zzzznotareal") is False


def test_one_unauthorized_source_does_not_fail_search(monkeypatch):
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_ACTION_API_URL",
        "http://action.example",
    )
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_CMS_API_URL",
        "http://cms.example",
    )
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_DMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None)
    meeting = SearchResultItem(
        id="42",
        title="Tower crane inspection",
        snippet="",
        content_type="meeting",
        url="",
        score=0.8,
        metadata={"source": "action", "entityType": "meeting", "entityId": "42"},
    )

    def meetings(*_args, **_kwargs):
        return [meeting]

    def cms(*_args, **_kwargs):
        request = httpx.Request("POST", "http://cms.example/api/search/advanced")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthenticated", request=request, response=response)

    with patch("app.search.space_module_search._search_meetings", meetings), patch(
        "app.search.space_module_search._search_cms", cms
    ):
        result = space_module_search(
            SearchRequest(query="crane", top_k=20, user_id="spoofed-user"),
            "space-jwt",
            correlation_id="trace-1",
        )

    assert result.partial is True
    assert len(result.results) == 1
    assert result.results[0].metadata["source"] == "action"
    statuses = {row.name: row.status for row in result.source_status}
    assert statuses["action.meeting"] == "ok"
    assert statuses["cms.contract"] == "unauthorized"
    assert all(item.url == "" for item in result.results)


def test_events_query_skips_cms(monkeypatch):
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_ACTION_API_URL",
        "http://action.example",
    )
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_CMS_API_URL",
        "http://cms.example",
    )
    meeting = SearchResultItem(
        id="8",
        title="ISO audit",
        snippet="",
        content_type="meeting",
        url="",
        score=0.4,
        metadata={"source": "action", "entityType": "meeting", "entityId": "8"},
    )
    cms_called = {"value": False}

    def meetings(*_args, **_kwargs):
        return [meeting]

    def cms(*_args, **_kwargs):
        cms_called["value"] = True
        return []

    with patch("app.search.space_module_search._search_meetings", meetings), patch(
        "app.search.space_module_search._search_cms", cms
    ):
        result = space_module_search(SearchRequest(query="events", top_k=20), "space-jwt")

    assert cms_called["value"] is False
    assert len(result.results) == 1
    assert result.results[0].title == "ISO audit"


def test_user_hash_is_stable_and_not_the_raw_id():
    assert hash_user_id("42") != "42"
    assert hash_user_id("42") == hash_user_id("42")
    assert hash_user_id("") == "anonymous"


def test_azure_discovery_off_returns_no_ids(monkeypatch):
    from app.search.azure_discovery import discover_entity_ids, is_azure_discovery_enabled

    monkeypatch.setattr("app.search.azure_discovery.settings.SPACE_AZURE_DISCOVERY", False)
    assert is_azure_discovery_enabled() is False
    assert discover_entity_ids("crane", "meeting", 20) == set()


def test_azure_hybrid_body_matches_poc_shape():
    from app.search.azure_discovery import CONTENT_TYPE_FILTER, VECTOR_FIELD, build_discovery_body

    body = build_discovery_body("crane inspection", "meeting", 20)
    assert body["search"] == "crane inspection"
    assert body["queryType"] == "semantic"
    assert body["semanticConfiguration"] == "default"
    assert "event" in body["filter"]
    assert VECTOR_FIELD == "content_vector"
    assert "event" in CONTENT_TYPE_FILTER["meeting"]


def test_azure_ids_from_space_index_prefer_event_id():
    from app.search.azure_discovery import ids_from_azure_rows

    ids = ids_from_azure_rows(
        [
            {
                "id": "space-event-42",
                "content_type": "event",
                "metadata": '{"event_id": 42, "record_id": "42", "table_name": "Events"}',
            },
            {
                "id": "space-agenda-9",
                "content_type": "event_agenda",
                "metadata": {"event_id": 42, "record_id": "9"},
            },
        ]
    )
    assert ids == {"42"}


def test_azure_ids_from_module_docs():
    from app.search.azure_discovery import classify_azure_kind, entity_from_azure_row, ids_from_azure_rows

    assert classify_azure_kind("contract", "space-contract-88") == "contract"
    assert classify_azure_kind("dms_document", "") == "document"
    assert classify_azure_kind("checkpoint_submission", "") == "checklist"
    eid, kind = entity_from_azure_row(
        {
            "id": "space-contract-88",
            "content_type": "contract",
            "metadata": {"projectCMId": 88, "projectId": 10},
        }
    )
    assert eid == "88"
    assert kind == "contract"
    assert ids_from_azure_rows(
        [{"id": "space-document-3", "content_type": "document", "metadata": {"documentId": 3}}]
    ) == {"3"}


def test_module_indexer_builds_contract_id():
    from app.search.space_module_indexer import _row_id, _title_content

    spec = {
        "content_type": "contract",
        "id_key": "projectCMId",
    }
    row = {"ProjectCMID": 88, "ProjectId": 10, "NameofContract": "Highway", "ContractNo": "C-1"}
    assert _row_id(row, spec) == "88"
    title, content = _title_content(row, spec)
    assert title == "Highway"
    assert "C-1" in content


def test_compact_azure_query_keeps_topic_word():
    from app.search.azure_discovery import _compact_search_query, ids_from_azure_rows, row_matches_terms

    assert _compact_search_query("what meetings mention crane?") == "crane"
    assert _compact_search_query("what contracts mention Contract Red?") == "red"
    assert _compact_search_query("what documents mention Demo test?") == "demo test"
    assert _compact_search_query("what incidents mention 2606/45?") == "2606 45"
    assert _compact_search_query("what checklists mention Site A?") == "site"
    assert ids_from_azure_rows(
        [{"id": "space-agenda-9", "metadata": {"event_id": 0, "record_id": "9"}}]
    ) == set()
    assert row_matches_terms(
        {"title": "Dimension — Event 9", "content": "Event information dimension"},
        ["crane"],
    ) is False
    assert row_matches_terms(
        {"title": "Weekly huddle", "content": "Agenda items: Tower crane inspection"},
        ["crane"],
    ) is True


def test_discover_skips_neighbors_when_keyword_misses(monkeypatch):
    from app.search import azure_discovery as ad

    monkeypatch.setattr(ad, "is_azure_discovery_enabled", lambda: True)
    monkeypatch.setattr(ad, "_index_name", lambda: "space-action-index")
    monkeypatch.setattr(ad, "_rest_rows", lambda *_a, **_k: [])
    monkeypatch.setattr(
        ad,
        "_poc_hybrid_rows",
        lambda *_a, **_k: [
            {
                "id": "space-event-9",
                "title": "3rd create event for meeting",
                "content": "Event information dimension",
                "content_type": "event",
                "metadata": {"event_id": 9},
            }
        ],
    )
    assert ad.discover_space_docs("what meetings mention crane?", "meeting", 20) == []


def test_space_answer_fallback_without_openai(monkeypatch):
    from app.search.space_answer import generate_space_answer, looks_like_question

    monkeypatch.setattr("app.search.space_answer.settings.AZURE_OPENAI_ENDPOINT", None)
    monkeypatch.setattr("app.search.space_answer.settings.AZURE_OPENAI_KEY", None)
    answer, questions = generate_space_answer(
        "crane",
        [
            SearchResultItem(
                id="42",
                title="Tower crane inspection",
                snippet="Safety",
                content_type="meeting",
                url="",
                metadata={"entityLabel": "Meeting"},
            )
        ],
    )
    assert "Tower crane inspection" in answer
    assert "BuildTrack" not in answer
    assert questions
    assert looks_like_question("what meetings are open?") is True
    assert looks_like_question("crane") is False


def test_envelope_items_reads_data_items():
    rows = _envelope_items({"data": {"items": [{"eventId": 1, "topic": "A"}]}})
    assert len(rows) == 1
    assert rows[0]["eventId"] == 1


def test_event_request_info_maps_agenda_match_without_title_keyword():
    hit = map_event_request_info(
        {
            "actionMeetingId": 42,
            "meetingNumber": "EVT-42",
            "title": "Weekly safety huddle",
            "categoryName": "HSE",
            "agendaItems": [{"title": "Tower crane inspection"}],
            "isAccessAvailable": True,
        },
        "what meetings mention crane?",
    )
    assert hit is not None
    assert hit.id == "42"
    assert hit.title == "Weekly safety huddle"
    assert "crane" in (hit.snippet or "").lower()


def test_event_request_info_skips_no_access():
    assert (
        map_event_request_info(
            {"actionMeetingId": 42, "title": "Secret", "isAccessAvailable": False},
            "crane",
        )
        is None
    )


def test_azure_ids_boost_matching_hits_but_keep_api_only_rows():
    from app.search.azure_discovery import boost_discovered_hits

    api_only = SearchResultItem(
        id="1",
        title="Api only",
        snippet="",
        content_type="meeting",
        url="",
        score=0.5,
        metadata={"source": "action", "entityType": "meeting", "entityId": "1"},
    )
    azure_hit = SearchResultItem(
        id="2",
        title="Also in azure",
        snippet="",
        content_type="meeting",
        url="",
        score=0.4,
        metadata={"source": "action", "entityType": "meeting", "entityId": "2"},
    )
    ranked = boost_discovered_hits([api_only, azure_hit], {"2"})
    assert ranked[0].id == "2"
    assert {row.id for row in ranked} == {"1", "2"}


def test_browse_events_skips_azure(monkeypatch):
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_ACTION_API_URL",
        "http://action.example",
    )
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_DMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.is_azure_discovery_enabled", lambda: True)
    azure_calls = {"n": 0}

    def azure(*_args, **_kwargs):
        azure_calls["n"] += 1
        return [{"entity_id": "99"}]

    meeting = SearchResultItem(
        id="8",
        title="ISO audit",
        snippet="",
        content_type="meeting",
        url="",
        score=0.4,
        metadata={"source": "action", "entityType": "meeting", "entityId": "8"},
    )
    monkeypatch.setattr("app.search.space_module_search.discover_space_docs", azure)
    with patch("app.search.space_module_search._search_meetings", lambda *_a, **_k: [meeting]):
        result = space_module_search(SearchRequest(query="events", top_k=20), "space-jwt")
    assert azure_calls["n"] == 0
    assert len(result.results) == 1


def test_free_text_runs_azure_hybrid_once(monkeypatch):
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_ACTION_API_URL",
        "http://action.example",
    )
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_DMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.is_azure_discovery_enabled", lambda: True)
    azure_calls: list[str] = []

    def azure(_query, content_type, _top_k):
        azure_calls.append(content_type)
        return [{"entity_id": "2", "snippet": "crane briefing"}]

    api_only = SearchResultItem(
        id="1",
        title="Api only",
        snippet="",
        content_type="meeting",
        url="",
        score=0.5,
        metadata={"source": "action", "entityType": "meeting", "entityId": "1"},
    )
    azure_hit = SearchResultItem(
        id="2",
        title="Also in azure",
        snippet="",
        content_type="meeting",
        url="",
        score=0.4,
        metadata={"source": "action", "entityType": "meeting", "entityId": "2"},
    )
    monkeypatch.setattr("app.search.space_module_search.discover_space_docs", azure)
    with patch("app.search.space_module_search._search_meetings", lambda *_a, **_k: [api_only, azure_hit]):
        result = space_module_search(SearchRequest(query="crane", top_k=20), "space-jwt")
    assert azure_calls == [""]
    assert result.results[0].id == "2"


def test_azure_ids_hydrate_when_list_search_empty(monkeypatch):
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_ACTION_API_URL",
        "http://action.example",
    )
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_DMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.is_azure_discovery_enabled", lambda: True)
    monkeypatch.setattr(
        "app.search.space_module_search.discover_space_docs",
        lambda *_a, **_k: [{"entity_id": "42", "snippet": "Tower crane inspection"}],
    )
    hydrated = SearchResultItem(
        id="42",
        title="Weekly safety huddle",
        snippet="Tower crane inspection",
        content_type="meeting",
        url="",
        score=0.4,
        metadata={"source": "action", "entityType": "meeting", "entityId": "42"},
    )
    with patch("app.search.space_module_search._search_meetings", lambda *_a, **_k: []), patch(
        "app.search.space_module_search._hydrate_meetings_from_azure",
        lambda *_a, **_k: [hydrated],
    ):
        result = space_module_search(
            SearchRequest(query="what meetings mention crane?", top_k=20),
            "space-jwt",
        )
    assert len(result.results) == 1
    assert result.results[0].id == "42"
    assert result.results[0].title == "Weekly safety huddle"


def test_azure_hydrates_contracts_from_typed_docs(monkeypatch):
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_ACTION_API_URL", None)
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_CMS_API_URL",
        "http://cms.example",
    )
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_DMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.is_azure_discovery_enabled", lambda: True)
    monkeypatch.setattr(
        "app.search.space_module_search.discover_space_docs",
        lambda *_a, **_k: [
            {"entity_id": "88", "kind": "contract", "snippet": "delay clause"}
        ],
    )
    hydrated = SearchResultItem(
        id="88",
        title="Highway contract",
        snippet="delay clause",
        content_type="contract",
        url="",
        score=0.4,
        metadata={"source": "cms", "entityType": "contract", "entityId": "88", "projectId": 10},
    )
    with patch("app.search.space_module_search._search_cms", lambda *_a, **_k: []), patch(
        "app.search.space_module_search._fetch_contract_by_id",
        lambda *_a, **_k: hydrated,
    ):
        result = space_module_search(
            SearchRequest(query="what contracts mention delay?", top_k=20),
            "space-jwt",
        )
    assert len(result.results) == 1
    assert result.results[0].id == "88"
    assert result.results[0].metadata["source"] == "cms"


def test_azure_hydrate_drops_meetings_that_do_not_mention_topic(monkeypatch):
    monkeypatch.setattr(
        "app.search.space_module_search.settings.SPACE_ACTION_API_URL",
        "http://action.example",
    )
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_DMS_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None)
    monkeypatch.setattr("app.search.space_module_search.is_azure_discovery_enabled", lambda: True)
    monkeypatch.setattr(
        "app.search.space_module_search.discover_space_docs",
        lambda *_a, **_k: [{"entity_id": "9", "snippet": ""}],
    )
    unrelated = SearchResultItem(
        id="9",
        title="3rd create event for meeting",
        snippet="Internal · Meeting",
        content_type="meeting",
        url="",
        score=0.4,
        metadata={"source": "action", "entityType": "meeting", "entityId": "9"},
    )
    with patch("app.search.space_module_search._search_meetings", lambda *_a, **_k: []), patch(
        "app.search.space_module_search._hydrate_meetings_from_azure",
        lambda *_a, **_k: [unrelated],
    ):
        result = space_module_search(
            SearchRequest(query="what meetings mention crane?", top_k=20),
            "space-jwt",
        )
    assert result.results == []


def test_all_sources_unauthorized_raises():
    request = httpx.Request("POST", "http://action.example/meetings")
    response = httpx.Response(401, request=request)

    def boom(*_args, **_kwargs):
        raise httpx.HTTPStatusError("unauthenticated", request=request, response=response)

    with patch("app.search.space_module_search.settings.SPACE_ACTION_API_URL", "http://action.example"), patch(
        "app.search.space_module_search.settings.SPACE_CMS_API_URL", None
    ), patch("app.search.space_module_search.settings.SPACE_DMS_API_URL", None), patch(
        "app.search.space_module_search.settings.SPACE_INCIDENT_API_URL", None
    ), patch("app.search.space_module_search.settings.SPACE_CHKWP_API_URL", None), patch(
        "app.search.space_module_search._search_meetings", boom
    ):
        with pytest.raises(PermissionError):
            space_module_search(SearchRequest(query="crane", top_k=20), "space-jwt")
