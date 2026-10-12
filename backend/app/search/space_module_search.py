"""SPACE header search: Azure hybrid ids, then module APIs with the SPACE JWT.

POC path: Azure AI Search finds candidate ids (agenda/body included). Those ids
are hydrated through Action/CMS/DMS with the caller's JWT so ACL stays on the
module APIs. Keyword list search is a fallback when Azure is empty.
Never emit SPACE page URLs. Do not log query text or titles.
"""
from __future__ import annotations

import copy
import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import httpx

from app.core.config import settings
from global_search_core.models import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SourceStatus,
)
from app.search.azure_discovery import (
    boost_discovered_hits,
    discover_space_docs,
    is_azure_discovery_enabled,
)
from app.search.space_auth import decode_space_token, space_user_id

log = logging.getLogger("space-module-search")

ACTION_KEY = "action.meeting"
CMS_KEY = "cms.contract"
DMS_KEY = "dms.document"
INCIDENT_KEY = "incident.incident"
CHKWP_KEY = "chkwp.checklist"
EVENT_NUMBER_RE = re.compile(r"^(?:evt|evn|mtg|act|ar)[-_/\s]?\d[\w-]*$", re.I)
MEETING_BROWSE = frozenset({"event", "events", "meeting", "meetings"})
CONTRACT_BROWSE = frozenset({"contract", "contracts", "cms"})
DOCUMENT_BROWSE = frozenset({"document", "documents", "dms"})
INCIDENT_BROWSE = frozenset({"incident", "incidents"})
CHECKLIST_BROWSE = frozenset({"checklist", "checklists", "permit", "permits", "chkwp"})
SEARCH_STOP_WORDS = frozenset(
    {
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "list",
        "show",
        "find",
        "tell",
        "is",
        "are",
        "was",
        "were",
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "for",
        "to",
        "my",
        "me",
        "please",
        "about",
        "any",
        "all",
        "open",
        "mention",
        "mentions",
        "mentioned",
        "regarding",
        "related",
        "with",
        "that",
        "this",
        "there",
        "can",
        "could",
        "would",
        "do",
        "does",
        "did",
        "and",
    }
    | MEETING_BROWSE
    | CONTRACT_BROWSE
    | DOCUMENT_BROWSE
    | INCIDENT_BROWSE
    | CHECKLIST_BROWSE
)
_SPACE_RESULT_CACHE: dict[str, tuple[float, SearchResponse]] = {}
_SPACE_RESULT_CACHE_TTL = 120.0

CMS_SEARCHABLE_FIELDS = (
    "projectName",
    "ProjectName",
    "verticalName",
    "VerticalName",
    "regionName",
    "RegionName",
    "projectStatus",
    "ProjectStatus",
    "title",
    "Title",
    "snippet",
    "Snippet",
    "content",
    "Content",
)


def is_space_module_search_configured() -> bool:
    return bool(
        settings.SPACE_ACTION_API_URL
        or settings.SPACE_CMS_API_URL
        or getattr(settings, "SPACE_DMS_API_URL", None)
        or getattr(settings, "SPACE_INCIDENT_API_URL", None)
        or getattr(settings, "SPACE_CHKWP_API_URL", None)
    )


def looks_like_event_number(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if re.fullmatch(r"\d{2,}", q):
        return True
    return bool(EVENT_NUMBER_RE.fullmatch(q))


def looks_like_meeting_browse(query: str) -> bool:
    return query.strip().lower() in MEETING_BROWSE


def looks_like_contract_browse(query: str) -> bool:
    return query.strip().lower() in CONTRACT_BROWSE


def looks_like_document_browse(query: str) -> bool:
    return query.strip().lower() in DOCUMENT_BROWSE


def looks_like_incident_browse(query: str) -> bool:
    return query.strip().lower() in INCIDENT_BROWSE


def looks_like_checklist_browse(query: str) -> bool:
    return query.strip().lower() in CHECKLIST_BROWSE


def extract_space_search_terms(query: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", query.strip().rstrip("?").lower())
    kept = [token for token in tokens if token not in SEARCH_STOP_WORDS]
    return " ".join(kept)


def _named_module_sources(query: str) -> list[str] | None:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    if tokens & MEETING_BROWSE:
        return [ACTION_KEY]
    if tokens & CONTRACT_BROWSE:
        return [CMS_KEY]
    if tokens & DOCUMENT_BROWSE:
        return [DMS_KEY]
    if tokens & INCIDENT_BROWSE:
        return [INCIDENT_KEY]
    if tokens & CHECKLIST_BROWSE:
        return [CHKWP_KEY]
    return None


def _fields_match_query(values: list[Any], query: str) -> bool:
    terms = extract_space_search_terms(query).split()
    if not terms:
        return not query.strip()
    hay = " ".join(str(value).lower() for value in values if isinstance(value, str))
    return all(term in hay for term in terms)


def _is_browse_query(query: str) -> bool:
    return (
        looks_like_meeting_browse(query)
        or looks_like_contract_browse(query)
        or looks_like_document_browse(query)
        or looks_like_incident_browse(query)
        or looks_like_checklist_browse(query)
    )


def _result_cache_key(query: str, user_hash: str, page_size: int, wanted: list[str]) -> str:
    raw = f"{query.strip().lower()}|{user_hash}|{page_size}|{','.join(wanted)}"
    return hashlib.md5(raw.encode()).hexdigest()


def looks_like_document_number(query: str) -> bool:
    q = query.strip()
    if re.fullmatch(r"\d{2,}", q):
        return True
    return bool(re.fullmatch(r"(?:doc|dms|d)[-_/\s]?\d[\w-]*", q, re.I))


def looks_like_incident_number(query: str) -> bool:
    q = query.strip()
    if re.fullmatch(r"\d{2,}", q):
        return True
    return bool(re.fullmatch(r"(?:inc|hse)[-_/\s]?\d[\w-]*", q, re.I))


def _logged_in_user_id(token: str) -> int:
    payload = decode_space_token(token)
    if not payload:
        return 0
    raw = space_user_id(payload)
    try:
        n = int(raw)
        return n if n > 0 else 0
    except ValueError:
        return 0


def _pick_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pick_num(*values: Any) -> Optional[int]:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip():
            try:
                return int(float(value))
            except ValueError:
                continue
    return None


def _score(query: str, title: str, identifier: str = "") -> float:
    q = (extract_space_search_terms(query) or query).strip().lower()
    t = (title or "").lower()
    ident = (identifier or "").lower()
    if not q:
        return 0.0
    if ident and ident == q:
        return 1.0
    if ident and q in ident:
        return 0.95
    if t == q:
        return 0.9
    if t.startswith(q):
        return 0.8
    if q in t:
        return 0.65
    return 0.4


def _auth_headers(token: str, correlation_id: str = "") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    return headers


def _timeout() -> httpx.Timeout:
    seconds = max(settings.SPACE_MODULE_SEARCH_TIMEOUT_SECONDS, 1.0)
    return httpx.Timeout(seconds)


def _is_unauthorized(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (401, 403)
    return False


def _envelope_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in ("result", "Result", "data", "Data"):
        block = data.get(key)
        if isinstance(block, list):
            return [row for row in block if isinstance(row, dict)]
        if isinstance(block, dict):
            items = block.get("items") if block.get("items") is not None else block.get("Items")
            if isinstance(items, list):
                return [row for row in items if isinstance(row, dict)]
    return []


def _envelope_object(data: Any) -> Optional[dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    for key in ("result", "Result", "data", "Data"):
        block = data.get(key)
        if isinstance(block, dict):
            return block
    return None


def _meeting_payload(topic: str, event_number: str, page_size: int) -> dict[str, Any]:
    return {
        "isSearchingFromMeeting": True,
        "meetingSearchModel": {
            "pageNumber": 1,
            "pageSize": page_size,
            "sortColumn": "",
            "sortOrder": "Desc",
            "assignmentOption": settings.SPACE_MEETING_ASSIGNMENT_OPTION,
            "startAndEndDate": "",
            "eventNumber": event_number,
            "presidedBy": "",
            "topic": topic,
            "raisedById": None,
            "eventCategoryId": [],
            "eventTypeIds": [],
            "eventSubTypeId": [],
            "selectedMeetingStatusId": [],
            "verticalIds": [],
            "regionIds": [],
            "projectIds": [],
            "selectedFunctionId": [],
            "selectedLevelId": [],
        },
    }


def map_meeting_item(item: dict[str, Any], query: str) -> Optional[SearchResultItem]:
    entity_id = _pick_num(item.get("eventId"), item.get("EventId"))
    if entity_id is None:
        return None
    event_number = _pick_str(item.get("eventNumber"), item.get("EventNumber"))
    title = _pick_str(item.get("topic"), item.get("Topic")) or event_number or f"Meeting {entity_id}"
    status = _pick_str(item.get("statusName"), item.get("StatusName"), item.get("statusItemName"))
    event_date = _pick_str(item.get("eventDate"), item.get("EventDate"))
    snippet = " · ".join(
        part
        for part in (
            _pick_str(item.get("categoryName"), item.get("CategoryName")),
            _pick_str(item.get("typeName"), item.get("TypeName")),
            _pick_str(item.get("presidedByName"), item.get("PresidedByName")),
        )
        if part
    )
    return SearchResultItem(
        id=str(entity_id),
        title=title,
        snippet=snippet,
        content_type="meeting",
        url="",
        score=_score(query, title, event_number),
        metadata={
            "source": "action",
            "entityType": "meeting",
            "entityId": str(entity_id),
            "entityLabel": "Meeting",
            "eventNumber": event_number or None,
            "eventDate": event_date or None,
            "statusName": status or None,
        },
    )


def map_event_request_info(info: dict[str, Any], query: str) -> Optional[SearchResultItem]:
    """Map GET GetEventRequestInfo into a header hit. Do not keyword-filter.

    Azure semantic hits may match agenda/body, not the meeting title.
    """
    if info.get("isAccessAvailable") is False or info.get("IsAccessAvailable") is False:
        return None
    entity_id = _pick_num(info.get("actionMeetingId"), info.get("ActionMeetingId"), info.get("eventId"), info.get("EventId"))
    if entity_id is None:
        return None
    agenda_titles: list[str] = []
    agendas = info.get("agendaItems") if info.get("agendaItems") is not None else info.get("AgendaItems")
    if isinstance(agendas, list):
        for row in agendas[:4]:
            if not isinstance(row, dict):
                continue
            title = _pick_str(row.get("title"), row.get("Title"))
            if title:
                agenda_titles.append(title)
    snippet_parts = [
        _pick_str(info.get("categoryName"), info.get("CategoryName")),
        _pick_str(info.get("typeName"), info.get("TypeName")),
        " · ".join(agenda_titles),
    ]
    hit = map_meeting_item(
        {
            "eventId": entity_id,
            "eventNumber": _pick_str(info.get("meetingNumber"), info.get("MeetingNumber")),
            "topic": _pick_str(info.get("title"), info.get("Title"), info.get("shortDescription"), info.get("ShortDescription")),
            "statusName": _pick_str(info.get("meetingStatus"), info.get("MeetingStatus")),
            "categoryName": snippet_parts[0],
            "typeName": snippet_parts[1],
            "presidedByName": snippet_parts[2] or _pick_str(info.get("requestedBy"), info.get("RequestedBy")),
        },
        query,
    )
    return hit


def cms_document_matches_query(doc: dict[str, Any], query: str) -> bool:
    return _fields_match_query([doc.get(field) for field in CMS_SEARCHABLE_FIELDS], query)


def map_cms_item(item: dict[str, Any], query: str) -> Optional[SearchResultItem]:
    project_cm_id = _pick_num(item.get("projectCMId"), item.get("ProjectCMId"))
    project_id = _pick_num(item.get("projectId"), item.get("ProjectId"))
    if project_cm_id is None or project_id is None:
        return None
    if item.get("noAccess") is True:
        return None
    title = (
        _pick_str(item.get("title"), item.get("Title"), item.get("projectName"), item.get("ProjectName"))
        or f"Contract {project_cm_id}"
    )
    snippet = _pick_str(item.get("snippet"), item.get("Snippet"), item.get("content"), item.get("Content"))
    if not snippet:
        snippet = " · ".join(
            part
            for part in (
                _pick_str(item.get("verticalName"), item.get("VerticalName")),
                _pick_str(item.get("regionName"), item.get("RegionName")),
                _pick_str(item.get("projectStatus"), item.get("ProjectStatus")),
            )
            if part
        )
    return SearchResultItem(
        id=str(project_cm_id),
        title=title,
        snippet=snippet,
        content_type="contract",
        url="",
        score=_score(query, title, str(project_cm_id)),
        metadata={
            "source": "cms",
            "entityType": "contract",
            "entityId": str(project_cm_id),
            "entityLabel": "Contract",
            "projectId": project_id,
            "projectCMId": project_cm_id,
        },
    )


def _hit_matches_terms(hit: SearchResultItem, query: str) -> bool:
    meta = hit.metadata or {}
    return _fields_match_query(
        [hit.title, hit.snippet, meta.get("eventNumber"), meta.get("statusName")],
        query,
    )


def _search_meetings_page(
    topic: str,
    event_number: str,
    query: str,
    token: str,
    page_size: int,
    correlation_id: str,
) -> list[SearchResultItem]:
    base = (settings.SPACE_ACTION_API_URL or "").rstrip("/")
    if not base:
        return []
    url = f"{base}/api/actionrequest/SearchEventAndTask"
    with httpx.Client(timeout=_timeout()) as client:
        response = client.post(
            url,
            json=_meeting_payload(topic, event_number, page_size),
            headers=_auth_headers(token, correlation_id),
        )
        response.raise_for_status()
        payload = response.json()
    items = _envelope_items(payload)
    if not items and isinstance(payload, dict):
        log.info(
            "meetings api empty envelope_keys=%s",
            ",".join(list(payload.keys())[:8]) or "none",
        )
    mapped: list[SearchResultItem] = []
    for item in items:
        hit = map_meeting_item(item, query)
        if hit is not None:
            mapped.append(hit)
    return mapped


def _fetch_meeting_by_id(
    event_id: str,
    query: str,
    token: str,
    correlation_id: str,
) -> Optional[SearchResultItem]:
    """Hydrate one Azure event id through Action (ACL). Skip 401/403/404."""
    base = (settings.SPACE_ACTION_API_URL or "").rstrip("/")
    if not base:
        return None
    eid = str(event_id).strip()
    if re.fullmatch(r"\d+", eid):
        url = f"{base}/api/actionrequest/GetEventRequestInfo/{eid}"
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.get(url, headers=_auth_headers(token, correlation_id))
            if response.status_code in (401, 403, 404):
                return None
            response.raise_for_status()
            info = _envelope_object(response.json())
            if info:
                hit = map_event_request_info(info, query)
                if hit is not None:
                    return hit
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403, 404):
                return None
            log.warning("azure hydrate event info failed", extra={"errorCode": "event_info_failed"})
            return None
        except Exception:
            log.warning("azure hydrate event info failed", extra={"errorCode": "event_info_failed"})
            return None
    try:
        hits = _search_meetings_page("", eid, query, token, 5, correlation_id)
    except Exception:
        return None
    for hit in hits:
        meta = hit.metadata or {}
        if str(meta.get("entityId") or hit.id) == eid:
            return hit
        if str(meta.get("eventNumber") or "").lower() == eid.lower():
            return hit
    return hits[0] if hits else None


def _hydrate_meetings_from_azure(
    event_ids: set[str],
    query: str,
    token: str,
    page_size: int,
    correlation_id: str,
) -> list[SearchResultItem]:
    ids = [str(eid).strip() for eid in event_ids if str(eid).strip()][: max(min(page_size, 8), 1)]
    if not ids:
        return []
    hits: list[SearchResultItem] = []
    workers = min(len(ids), 4)
    timeout_s = max(settings.SPACE_MODULE_SEARCH_TIMEOUT_SECONDS, 2.0) + 1.0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="azure-hydrate") as pool:
        futs = [pool.submit(_fetch_meeting_by_id, eid, query, token, correlation_id) for eid in ids]
        for fut in futs:
            try:
                hit = fut.result(timeout=timeout_s)
            except Exception:
                hit = None
            if hit is not None:
                hits.append(hit)
    log.info("azure hydrate meetings extra=%s requested=%s", len(hits), len(ids))
    return hits


def _get_module_object(url: str, token: str, correlation_id: str) -> Optional[dict[str, Any]]:
    try:
        with httpx.Client(timeout=_timeout()) as client:
            response = client.get(url, headers=_auth_headers(token, correlation_id))
        if response.status_code in (401, 403, 404):
            return None
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            return None
        if isinstance(payload, dict) and payload.get("isSuccess") is False:
            return None
        return _envelope_object(payload) if isinstance(payload, dict) else None
    except Exception:
        return None


def _fetch_contract_by_id(entity_id: str, query: str, token: str, correlation_id: str) -> Optional[SearchResultItem]:
    base = (settings.SPACE_CMS_API_URL or "").rstrip("/")
    if not base or not re.fullmatch(r"\d+", str(entity_id).strip()):
        return None
    info = _get_module_object(
        f"{base}/api/contract-header/details?Id={entity_id}", token, correlation_id
    )
    if not info:
        return None
    return map_cms_item(
        {
            "projectCMId": info.get("projectCMId") or info.get("ProjectCMId") or entity_id,
            "projectId": info.get("projectId") or info.get("ProjectId"),
            "title": _pick_str(info.get("nameofContract"), info.get("NameofContract")),
            "snippet": _pick_str(info.get("contractNo"), info.get("ContractNo"), info.get("employerName"), info.get("EmployerName")),
            "noAccess": info.get("noAccess"),
        },
        query,
    )


def _fetch_document_by_id(entity_id: str, query: str, token: str, correlation_id: str) -> Optional[SearchResultItem]:
    base = (getattr(settings, "SPACE_DMS_API_URL", None) or "").rstrip("/")
    if not base or not re.fullmatch(r"\d+", str(entity_id).strip()):
        return None
    info = _get_module_object(f"{base}/api/document/{entity_id}", token, correlation_id)
    if not info or not _dms_authorized(info):
        return None
    access = _pick_str(info.get("accessType"), info.get("AccessType"))
    if access.lower() == "noaccess":
        return None
    return map_dms_item(info, query)


def _fetch_incident_by_id(entity_id: str, query: str, token: str, correlation_id: str) -> Optional[SearchResultItem]:
    base = (getattr(settings, "SPACE_INCIDENT_API_URL", None) or "").rstrip("/")
    if not base or not re.fullmatch(r"\d+", str(entity_id).strip()):
        return None
    info = _get_module_object(
        f"{base}/api/information/details?IncidentId={entity_id}", token, correlation_id
    )
    if not info:
        return None
    return map_incident_item(info, query)


def _fetch_checklist_by_id(entity_id: str, query: str, token: str, correlation_id: str) -> Optional[SearchResultItem]:
    base = (getattr(settings, "SPACE_CHKWP_API_URL", None) or "").rstrip("/")
    if not base or not re.fullmatch(r"\d+", str(entity_id).strip()):
        return None
    info = _get_module_object(
        f"{base}/api/submission/full-details?id={entity_id}", token, correlation_id
    )
    if not info:
        return None
    return map_checklist_item(
        {
            "submissionId": info.get("submissionId") or info.get("SubmissionId") or entity_id,
            "submissionNumber": _pick_str(info.get("submissionNumber"), info.get("SubmissionNumber")),
            "chkwpName": _pick_str(info.get("templateName"), info.get("TemplateName"), info.get("chkwpName")),
            "category": _pick_str(info.get("templateTypeName"), info.get("TemplateTypeName")),
            "type": _pick_str(info.get("subType"), info.get("SubType")),
            "project": _pick_str(info.get("projectName"), info.get("ProjectName")),
            "status": _pick_str(info.get("statusName"), info.get("StatusName"), info.get("status")),
        },
        query,
    )


def _hydrate_ids(
    fetch,
    entity_ids: set[str],
    query: str,
    token: str,
    page_size: int,
    correlation_id: str,
    label: str,
) -> list[SearchResultItem]:
    ids = [str(eid).strip() for eid in entity_ids if str(eid).strip()][: max(min(page_size, 8), 1)]
    if not ids:
        return []
    hits: list[SearchResultItem] = []
    workers = min(len(ids), 4)
    timeout_s = max(settings.SPACE_MODULE_SEARCH_TIMEOUT_SECONDS, 2.0) + 1.0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"azure-hydrate-{label}") as pool:
        futs = [pool.submit(fetch, eid, query, token, correlation_id) for eid in ids]
        for fut in futs:
            try:
                hit = fut.result(timeout=timeout_s)
            except Exception:
                hit = None
            if hit is not None:
                hits.append(hit)
    log.info("azure hydrate %s extra=%s requested=%s", label, len(hits), len(ids))
    return hits


KIND_SOURCE = {
    "meeting": "action",
    "contract": "cms",
    "document": "dms",
    "incident": "incident",
    "checklist": "chkwp",
}
SOURCE_KIND = {value: key for key, value in KIND_SOURCE.items()}


def _search_meetings(query: str, token: str, page_size: int, correlation_id: str = "") -> list[SearchResultItem]:
    if looks_like_meeting_browse(query):
        return _search_meetings_page("", "", query, token, page_size, correlation_id)
    if not looks_like_event_number(query):
        terms = extract_space_search_terms(query) or query
        by_topic = _search_meetings_page(terms, "", query, token, page_size, correlation_id)
        matched = [hit for hit in by_topic if _hit_matches_terms(hit, query)]
        if matched:
            return matched
        return [
            hit
            for hit in _search_meetings_page("", "", query, token, page_size, correlation_id)
            if _hit_matches_terms(hit, query)
        ]

    by_number = _search_meetings_page("", query, query, token, page_size, correlation_id)
    if by_number:
        return by_number
    by_topic = _search_meetings_page(query, "", query, token, page_size, correlation_id)
    if by_topic:
        return by_topic
    digits = re.search(r"(\d[\d-]*)$", query.strip())
    if digits:
        cleaned = digits.group(1).rstrip("-")
        if cleaned and cleaned != query:
            return _search_meetings_page("", cleaned, query, token, page_size, correlation_id)
    return []


def _cms_payload(query: str, page_size: int) -> dict[str, Any]:
    return {
        "verticalIds": [],
        "regionIds": [],
        "projectIds": [],
        "projectInfo": "",
        "statusIds": [],
        "contractualDateFrom": None,
        "contractualDateTo": None,
        "actualDateFrom": None,
        "actualDateTo": None,
        "completionDateFrom": None,
        "completionDateTo": None,
        "sectorIds": [],
        "clientTypeIds": [],
        "contractModelIds": [],
        "contractTypeIds": [],
        "contractInfo": query,
        "contractDocInfo": "",
        "contractConditionIds": [],
        "contractClauseInfo": "",
        "classificationIds": [],
        "subClassificationIds": [],
        "disputeInfo": "",
        "actionInfo": "",
        "statusTypeIds": [],
        "disputeStageIds": [],
        "communicationInfo": "",
        "communicationTypeIds": [],
        "documentInfo": "",
        "documentTypeIds": [],
        "registerInfo": "",
        "registerTypeIds": [],
        "pageIndex": 1,
        "pageSize": page_size,
    }


def _search_cms(query: str, token: str, page_size: int, correlation_id: str = "") -> list[SearchResultItem]:
    base = (settings.SPACE_CMS_API_URL or "").rstrip("/")
    if not base:
        return []
    browse = looks_like_contract_browse(query)
    api_query = "" if browse else (extract_space_search_terms(query) or query)
    url = f"{base}/api/search/advanced"
    with httpx.Client(timeout=_timeout()) as client:
        response = client.post(
            url, json=_cms_payload(api_query, page_size), headers=_auth_headers(token, correlation_id)
        )
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict) and data.get("isSuccess") is False:
        raise RuntimeError(data.get("message") or "CMS contract search failed")
    items = _envelope_items(data)
    mapped: list[SearchResultItem] = []
    for item in items:
        if not browse and not cms_document_matches_query(item, query):
            continue
        hit = map_cms_item(item, query)
        if hit is not None:
            mapped.append(hit)
    return mapped


def _dms_authorized(item: dict[str, Any]) -> bool:
    if item.get("noAccess") is True or item.get("NoAccess") is True:
        return False
    matrix = item.get("accessMatrix") or item.get("AccessMatrix") or {}
    if isinstance(matrix, dict) and matrix.get("noAccess") is True:
        return False
    if item.get("isAccess") is False or item.get("IsAccess") is False:
        return False
    return True


def _dms_matches(item: dict[str, Any], query: str) -> bool:
    return _fields_match_query(
        [
            item.get("title"),
            item.get("Title"),
            item.get("documentNumber"),
            item.get("DocumentNumber"),
            item.get("fileName"),
            item.get("FileName"),
            item.get("masterKeyword"),
            item.get("MasterKeyword"),
            item.get("customKeyword"),
            item.get("CustomKeyword"),
            item.get("contentInformation"),
            item.get("ContentInformation"),
        ],
        query,
    )


def map_dms_item(item: dict[str, Any], query: str) -> Optional[SearchResultItem]:
    entity_id = _pick_num(item.get("documentId"), item.get("DocumentId"))
    if entity_id is None:
        return None
    number = _pick_str(item.get("documentNumber"), item.get("DocumentNumber"))
    title = _pick_str(item.get("title"), item.get("Title")) or number or f"Document {entity_id}"
    snippet = _pick_str(item.get("fileName"), item.get("FileName"), item.get("masterKeyword"))
    return SearchResultItem(
        id=str(entity_id),
        title=title,
        snippet=snippet,
        content_type="document",
        url="",
        score=_score(query, title, number),
        metadata={
            "source": "dms",
            "entityType": "document",
            "entityId": str(entity_id),
            "entityLabel": "Document",
            "documentNumber": number or None,
        },
    )


def _search_dms(query: str, token: str, page_size: int, correlation_id: str = "") -> list[SearchResultItem]:
    base = (getattr(settings, "SPACE_DMS_API_URL", None) or "").rstrip("/")
    if not base:
        return []
    user_id = _logged_in_user_id(token)
    if user_id <= 0:
        return []
    browse = looks_like_document_browse(query)
    by_number = not browse and looks_like_document_number(query)
    payload = {
        "pageNumber": 1,
        "pageSize": page_size,
        "loggedInUserId": user_id,
        "sortBy": "lastUpdatedDate",
        "sortDirection": "desc",
        "title": "" if browse or by_number else (extract_space_search_terms(query) or query),
        "contentInformation": "",
        "createdByUserId": 0,
        "updatedByUserId": 0,
        "positionIds": [0],
        "levelIds": [0],
        "verticalIds": [0],
        "regionIds": [0],
        "projectIds": [0],
        "functionIds": [0],
        "fileName": "",
        "documentNumber": query if by_number else "",
        "sharedWith": "",
        "keywords": "",
        "fromDocumentDate": "",
        "toDocumentDate": "",
        "fromUploadedOn": "",
        "toUploadedOn": "",
        "fromUpdatedOn": "",
        "toUpdatedOn": "",
        "isAccess": True,
    }
    url = f"{base}/api/document/search"
    with httpx.Client(timeout=_timeout()) as client:
        response = client.post(url, json=payload, headers=_auth_headers(token, correlation_id))
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict) and data.get("isSuccess") is False:
        raise RuntimeError(data.get("message") or "DMS document search failed")
    mapped: list[SearchResultItem] = []
    for item in _envelope_items(data):
        if not _dms_authorized(item):
            continue
        if not browse and not _dms_matches(item, query):
            continue
        hit = map_dms_item(item, query)
        if hit is not None:
            mapped.append(hit)
    return mapped


def map_incident_item(item: dict[str, Any], query: str) -> Optional[SearchResultItem]:
    entity_id = _pick_num(item.get("incidentId"), item.get("IncidentId"))
    if entity_id is None:
        return None
    number = _pick_str(item.get("incidentNumber"), item.get("IncidentNumber"))
    type_name = _pick_str(item.get("incidentTypeName"), item.get("IncidentTypeName"))
    title = number or type_name or f"Incident {entity_id}"
    snippet = " · ".join(
        part
        for part in (
            _pick_str(item.get("projectName"), item.get("ProjectName")),
            _pick_str(item.get("regionName"), item.get("RegionName")),
        )
        if part
    )
    return SearchResultItem(
        id=str(entity_id),
        title=title,
        snippet=snippet,
        content_type="incident",
        url="",
        score=_score(query, title, number),
        metadata={
            "source": "incident",
            "entityType": "incident",
            "entityId": str(entity_id),
            "entityLabel": "Incident",
            "incidentNumber": number or None,
        },
    )


def _search_incident(query: str, token: str, page_size: int, correlation_id: str = "") -> list[SearchResultItem]:
    base = (getattr(settings, "SPACE_INCIDENT_API_URL", None) or "").rstrip("/")
    if not base:
        return []
    browse = looks_like_incident_browse(query)
    by_number = not browse and looks_like_incident_number(query)
    payload = {
        "pageNumber": 1,
        "pageSize": page_size,
        "sortBy": "modifiedDate",
        "sortDirection": "desc",
        "search": "" if browse or by_number else (extract_space_search_terms(query) or query),
        "functionIds": None,
        "levelIds": None,
        "verticalIds": None,
        "regionIds": None,
        "projectIds": None,
        "locationIds": None,
        "incidentStatusIds": None,
        "primaryIncidentTypeIds": None,
        "incidentNumber": query if by_number else None,
        "incidentDateFrom": None,
        "incidentDateTo": None,
        "actionByUserId": None,
        "raisedByUserId": None,
        "escalatedToUserId": None,
        "assignmentFilter": None,
    }
    url = f"{base}/api/information/list"
    with httpx.Client(timeout=_timeout()) as client:
        response = client.post(url, json=payload, headers=_auth_headers(token, correlation_id))
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict) and data.get("isSuccess") is False:
        raise RuntimeError(data.get("message") or "Incident search failed")
    mapped: list[SearchResultItem] = []
    for item in _envelope_items(data):
        hit = map_incident_item(item, query)
        if hit is not None:
            mapped.append(hit)
    return mapped


def _checklist_authorized(item: dict[str, Any]) -> bool:
    access = _pick_str(item.get("submissionAccess"), item.get("SubmissionAccess")).upper()
    return access != "NOACCESS"


def _checklist_matches(item: dict[str, Any], query: str) -> bool:
    return _fields_match_query(
        [
            item.get("submissionNumber"),
            item.get("SubmissionNumber"),
            item.get("chkwpName"),
            item.get("ChkwpName"),
            item.get("category"),
            item.get("Category"),
            item.get("type"),
            item.get("Type"),
            item.get("project"),
            item.get("Project"),
            item.get("status"),
            item.get("Status"),
        ],
        query,
    )


def map_checklist_item(item: dict[str, Any], query: str) -> Optional[SearchResultItem]:
    entity_id = _pick_num(item.get("submissionId"), item.get("SubmissionId"))
    if entity_id is None:
        return None
    number = _pick_str(item.get("submissionNumber"), item.get("SubmissionNumber"))
    name = _pick_str(item.get("chkwpName"), item.get("ChkwpName"))
    title = name or number or f"Checklist {entity_id}"
    snippet = " · ".join(
        part
        for part in (
            _pick_str(item.get("category"), item.get("Category")),
            _pick_str(item.get("type"), item.get("Type")),
        )
        if part
    )
    return SearchResultItem(
        id=str(entity_id),
        title=title,
        snippet=snippet,
        content_type="checklist",
        url="",
        score=_score(query, title, number),
        metadata={
            "source": "chkwp",
            "entityType": "checklist",
            "entityId": str(entity_id),
            "entityLabel": "Checklist",
            "submissionNumber": number or None,
        },
    )


def _search_checklist(query: str, token: str, page_size: int, correlation_id: str = "") -> list[SearchResultItem]:
    base = (getattr(settings, "SPACE_CHKWP_API_URL", None) or "").rstrip("/")
    if not base:
        return []
    browse = looks_like_checklist_browse(query)
    payload = {
        "assignmentOption": "AssignedToMe",
        "sortColumn": "CreatedDate",
        "sortOrder": "desc",
        "pageNumber": 1,
        "pageSize": page_size,
        "functionId": None,
        "levelId": None,
        "categoryId": None,
        "typeId": None,
        "chkwpNameId": None,
        "submissionNumber": None if browse else (extract_space_search_terms(query) or query),
        "locationId": None,
        "statusId": None,
        "startDate": None,
        "endDate": None,
        "projectIds": None,
        "regionIds": None,
        "verticalIds": None,
        "actionByUserId": None,
        "raisedByUserId": None,
    }
    url = f"{base}/api/submission/search-checklistWorkPermitEndUser"
    with httpx.Client(timeout=_timeout()) as client:
        response = client.post(url, json=payload, headers=_auth_headers(token, correlation_id))
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict) and data.get("isSuccess") is False:
        raise RuntimeError(data.get("message") or "Checklist search failed")
    mapped: list[SearchResultItem] = []
    for item in _envelope_items(data):
        if not _checklist_authorized(item):
            continue
        if not browse and not _checklist_matches(item, query):
            continue
        hit = map_checklist_item(item, query)
        if hit is not None:
            mapped.append(hit)
    return mapped


def _run_source(name: str, fn) -> tuple[list[SearchResultItem], SourceStatus]:
    started = time.perf_counter()
    try:
        hits = fn()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return hits, SourceStatus(name=name, status="ok", latency_ms=latency_ms, count=len(hits))
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        if isinstance(exc, httpx.TimeoutException):
            status = "timeout"
            message = "Source timed out"
        elif _is_unauthorized(exc):
            status = "unauthorized"
            message = "Not authorized for this source"
        else:
            status = "error"
            message = "Source failed"
        log.warning("space source failed", extra={"source": name, "status": status, "latency_ms": latency_ms})
        return [], SourceStatus(
            name=name,
            status=status,
            latency_ms=latency_ms,
            count=0,
            message=message,
        )


def space_module_search(
    request: SearchRequest,
    bearer_token: str,
    *,
    correlation_id: str = "",
    user_hash: str = "anonymous",
) -> SearchResponse:
    query = request.query.strip()
    if not query:
        raise ValueError("Query cannot be empty")
    if len(query) > 500:
        raise ValueError("Query is too long")
    if not bearer_token.strip():
        raise PermissionError("Authentication required")

    page_size = request.top_k
    requested = [key for key in (request.source_ids or []) if key]
    if requested:
        wanted = requested
    elif looks_like_meeting_browse(query):
        wanted = [ACTION_KEY]
    elif looks_like_contract_browse(query):
        wanted = [CMS_KEY]
    elif looks_like_document_browse(query):
        wanted = [DMS_KEY]
    elif looks_like_incident_browse(query):
        wanted = [INCIDENT_KEY]
    elif looks_like_checklist_browse(query):
        wanted = [CHKWP_KEY]
    else:
        wanted = _named_module_sources(query) or [
            ACTION_KEY,
            CMS_KEY,
            DMS_KEY,
            INCIDENT_KEY,
            CHKWP_KEY,
        ]

    cache_key = _result_cache_key(query, user_hash, page_size, wanted)
    cached = _SPACE_RESULT_CACHE.get(cache_key)
    if cached:
        ts, response = cached
        if time.time() - ts < _SPACE_RESULT_CACHE_TTL:
            return copy.deepcopy(response)

    jobs: dict[str, Any] = {}
    if ACTION_KEY in wanted and settings.SPACE_ACTION_API_URL:
        jobs[ACTION_KEY] = lambda: _search_meetings(query, bearer_token, page_size, correlation_id)
    if CMS_KEY in wanted and settings.SPACE_CMS_API_URL:
        jobs[CMS_KEY] = lambda: _search_cms(query, bearer_token, page_size, correlation_id)
    if DMS_KEY in wanted and getattr(settings, "SPACE_DMS_API_URL", None):
        jobs[DMS_KEY] = lambda: _search_dms(query, bearer_token, page_size, correlation_id)
    if INCIDENT_KEY in wanted and getattr(settings, "SPACE_INCIDENT_API_URL", None):
        jobs[INCIDENT_KEY] = lambda: _search_incident(query, bearer_token, page_size, correlation_id)
    if CHKWP_KEY in wanted and getattr(settings, "SPACE_CHKWP_API_URL", None):
        jobs[CHKWP_KEY] = lambda: _search_checklist(query, bearer_token, page_size, correlation_id)

    started = time.perf_counter()
    results: list[SearchResultItem] = []
    statuses: list[SourceStatus] = []
    run_azure = is_azure_discovery_enabled() and not _is_browse_query(query)
    azure_filter = ""
    if run_azure and wanted == [ACTION_KEY]:
        azure_filter = "meeting"
    elif run_azure and wanted == [CMS_KEY]:
        azure_filter = "contract"
    elif run_azure and wanted == [DMS_KEY]:
        azure_filter = "document"
    elif run_azure and wanted == [INCIDENT_KEY]:
        azure_filter = "incident"
    elif run_azure and wanted == [CHKWP_KEY]:
        azure_filter = "checklist"
    worker_count = max(len(jobs) + (1 if run_azure else 0), 1)
    discovered: set[str] = set()
    azure_passages: dict[str, str] = {}
    hydrated_ids: set[str] = set()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {name: pool.submit(_run_source, name, fn) for name, fn in jobs.items()}
        azure_future = (
            pool.submit(discover_space_docs, query, azure_filter, page_size) if run_azure else None
        )
        for name, future in futures.items():
            hits, status = future.result()
            results.extend(hits)
            statuses.append(status)
        azure_docs: list[dict[str, Any]] = []
        if azure_future is not None:
            try:
                azure_docs = azure_future.result(timeout=15) or []
            except Exception:
                log.warning("azure discovery skipped", extra={"errorCode": "azure_discovery_failed"})
            if azure_filter and not azure_docs:
                try:
                    azure_docs = discover_space_docs(query, "", page_size) or []
                except Exception:
                    log.warning("azure discovery skipped", extra={"errorCode": "azure_discovery_failed"})
            discovered = {str(doc["entity_id"]) for doc in azure_docs if doc.get("entity_id")}
            azure_passages = {
                f"{doc.get('kind') or 'meeting'}:{doc['entity_id']}": str(doc.get("snippet") or "")
                for doc in azure_docs
                if doc.get("entity_id") and doc.get("snippet")
            }
            id_preview = ",".join(f"{doc.get('kind')}:{doc.get('entity_id')}" for doc in azure_docs[:12]) or "none"
            log.info("azure discovery complete ids=%s count=%s", id_preview, len(azure_docs))

    extra: list[SearchResultItem] = []
    by_kind: dict[str, set[str]] = {}
    for doc in azure_docs:
        kind = str(doc.get("kind") or "meeting")
        eid = str(doc.get("entity_id") or "")
        if eid:
            by_kind.setdefault(kind, set()).add(eid)

    if ACTION_KEY in wanted and by_kind.get("meeting") and settings.SPACE_ACTION_API_URL:
        have = {
            str((item.metadata or {}).get("entityId") or item.id)
            for item in results
            if (item.metadata or {}).get("source") == "action"
        }
        missing = by_kind["meeting"] - have
        if missing:
            extra.extend(
                _hydrate_meetings_from_azure(missing, query, bearer_token, page_size, correlation_id)
            )
    if CMS_KEY in wanted and by_kind.get("contract") and settings.SPACE_CMS_API_URL:
        have = {
            str((item.metadata or {}).get("entityId") or item.id)
            for item in results
            if (item.metadata or {}).get("source") == "cms"
        }
        extra.extend(
            _hydrate_ids(
                _fetch_contract_by_id,
                by_kind["contract"] - have,
                query,
                bearer_token,
                page_size,
                correlation_id,
                "contracts",
            )
        )
    if DMS_KEY in wanted and by_kind.get("document") and getattr(settings, "SPACE_DMS_API_URL", None):
        have = {
            str((item.metadata or {}).get("entityId") or item.id)
            for item in results
            if (item.metadata or {}).get("source") == "dms"
        }
        extra.extend(
            _hydrate_ids(
                _fetch_document_by_id,
                by_kind["document"] - have,
                query,
                bearer_token,
                page_size,
                correlation_id,
                "documents",
            )
        )
    if INCIDENT_KEY in wanted and by_kind.get("incident") and getattr(settings, "SPACE_INCIDENT_API_URL", None):
        have = {
            str((item.metadata or {}).get("entityId") or item.id)
            for item in results
            if (item.metadata or {}).get("source") == "incident"
        }
        extra.extend(
            _hydrate_ids(
                _fetch_incident_by_id,
                by_kind["incident"] - have,
                query,
                bearer_token,
                page_size,
                correlation_id,
                "incidents",
            )
        )
    if CHKWP_KEY in wanted and by_kind.get("checklist") and getattr(settings, "SPACE_CHKWP_API_URL", None):
        have = {
            str((item.metadata or {}).get("entityId") or item.id)
            for item in results
            if (item.metadata or {}).get("source") == "chkwp"
        }
        extra.extend(
            _hydrate_ids(
                _fetch_checklist_by_id,
                by_kind["checklist"] - have,
                query,
                bearer_token,
                page_size,
                correlation_id,
                "checklists",
            )
        )
    hydrated_ids = {str(hit.id) for hit in extra}
    results.extend(extra)

    for item in results:
        eid = str((item.metadata or {}).get("entityId") or item.id)
        kind = SOURCE_KIND.get(str((item.metadata or {}).get("source") or ""), "meeting")
        passage = azure_passages.get(f"{kind}:{eid}") or azure_passages.get(eid)
        if not passage:
            continue
        snippet = item.snippet or ""
        if passage.lower() in snippet.lower():
            continue
        item.snippet = f"{snippet} · {passage}".strip(" ·")[:320] if snippet else passage[:280]

    if not jobs:
        statuses.append(SourceStatus(name="space", status="skipped", message="No SPACE module URLs configured"))

    unauthorized_only = bool(statuses) and all(s.status == "unauthorized" for s in statuses)
    if unauthorized_only:
        raise PermissionError("Authentication required")

    seen: dict[str, SearchResultItem] = {}
    for item in results:
        meta = item.metadata or {}
        key = f"{meta.get('source')}.{meta.get('entityType')}.{meta.get('entityId') or item.id}"
        existing = seen.get(key)
        if existing is None or (item.score or 0) > (existing.score or 0):
            seen[key] = item
    ranked = sorted(seen.values(), key=lambda row: (-(row.score or 0), row.title.lower()))
    if discovered:
        ranked = boost_discovered_hits(ranked, discovered)
    topic = extract_space_search_terms(query)
    if topic and not _is_browse_query(query) and not looks_like_event_number(query):
        ranked = [
            row
            for row in ranked
            if str(row.id) not in hydrated_ids or _hit_matches_terms(row, query)
        ]
    hits = ranked[:page_size]
    partial = any(s.status != "ok" for s in statuses)
    took_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "space module search complete hits=%s partial=%s sources=%s",
        len(hits),
        partial,
        len(statuses),
    )
    response = SearchResponse(
        ai_answer="",
        results=hits,
        suggested_questions=[],
        search_time_ms=took_ms,
        total_results=len(ranked),
        is_question=False,
        sources_searched=[s.name for s in statuses],
        partial=partial,
        source_status=statuses,
        correlation_id=correlation_id or None,
    )
    if hits:
        _SPACE_RESULT_CACHE[cache_key] = (time.time(), copy.deepcopy(response))
        if len(_SPACE_RESULT_CACHE) > 200:
            oldest = sorted(_SPACE_RESULT_CACHE.items(), key=lambda item: item[1][0])[:50]
            for key, _ in oldest:
                del _SPACE_RESULT_CACHE[key]
    return response
