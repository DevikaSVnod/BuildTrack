"""SPACE Azure AI Search — same hybrid retrieval as the POC.

POC path: BM25 + semantic rank + Azure OpenAI embeddings (content_vector).
Module APIs + SPACE JWT stay the source of truth. Azure only supplies ids
for ranking. If Azure is off, empty, or fails, search still returns API hits.
Do not log the query text. Do not query SPACE SQL from this module.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger("space-azure-discovery")

VECTOR_FIELD = "content_vector"
_DOC_ID_EVENT_RE = re.compile(r"space-event-(\d+)", re.I)
_DOC_ID_KIND_RE = (
    (re.compile(r"space-contract-(\d+)", re.I), "contract"),
    (re.compile(r"space-document-(\d+)", re.I), "document"),
    (re.compile(r"space-incident-(\d+)", re.I), "incident"),
    (re.compile(r"space-checklist-(\d+)", re.I), "checklist"),
    (re.compile(r"space-event-(\d+)", re.I), "meeting"),
)

KIND_FROM_CONTENT = {
    "event": "meeting",
    "event_agenda": "meeting",
    "event_information": "meeting",
    "meeting": "meeting",
    "contract": "contract",
    "cms": "contract",
    "document": "document",
    "dms": "document",
    "dms_document": "document",
    "incident": "incident",
    "checklist": "checklist",
    "chkwp": "checklist",
    "checkpoint_submission": "checklist",
}

# SPACE index uses event / event_agenda / event_information (space_indexer).
CONTENT_TYPE_FILTER = {
    "meeting": (
        "content_type eq 'event' or content_type eq 'event_agenda' "
        "or content_type eq 'event_information' or content_type eq 'meeting'"
    ),
    "contract": "content_type eq 'contract' or content_type eq 'cms'",
    "document": (
        "content_type eq 'document' or content_type eq 'dms' "
        "or content_type eq 'dms_document'"
    ),
    "incident": "content_type eq 'incident'",
    "checklist": (
        "content_type eq 'checklist' or content_type eq 'chkwp' "
        "or content_type eq 'checkpoint_submission'"
    ),
}


def is_azure_discovery_enabled() -> bool:
    return bool(
        settings.SPACE_AZURE_DISCOVERY
        and settings.AZURE_SEARCH_ENDPOINT
        and settings.AZURE_SEARCH_KEY
        and (settings.SPACE_AZURE_INDEX or settings.AZURE_SEARCH_SPACE_INDEX)
    )


def _index_name() -> str:
    return (settings.SPACE_AZURE_INDEX or settings.AZURE_SEARCH_SPACE_INDEX or "").strip()


def build_discovery_body(query: str, content_type: str, top_k: int) -> dict[str, Any]:
    """REST shape used only if the Azure SDK path is unavailable.

    Preferred retrieval is SDK hybrid (embed + semantic + BM25) because the
    SPACE index stores precomputed content_vector from Azure OpenAI, not
    integrated vectorization (vectorQueries kind=text).
    """
    k = max(min(top_k, 50), 1)
    body: dict[str, Any] = {
        "search": query.strip(),
        "searchMode": "any",
        "top": k,
        "select": "id,title,content,content_type,metadata",
        "queryType": "semantic",
        "semanticConfiguration": "default",
        "queryCaption": "extractive",
    }
    extra_filter = CONTENT_TYPE_FILTER.get(content_type)
    if extra_filter:
        body["filter"] = extra_filter
    return body


def _keyword_only_body(query: str, content_type: str, top_k: int) -> dict[str, Any]:
    body = {
        "search": query.strip(),
        "searchMode": "any",
        "top": max(min(top_k, 50), 1),
        "select": "id,title,content,content_type,metadata",
    }
    extra_filter = CONTENT_TYPE_FILTER.get(content_type)
    if extra_filter:
        body["filter"] = extra_filter
    return body


def _as_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def classify_azure_kind(content_type: str, doc_id: str = "") -> str:
    kind = KIND_FROM_CONTENT.get((content_type or "").strip().lower())
    if kind:
        return kind
    for pattern, mapped in _DOC_ID_KIND_RE:
        if pattern.search(doc_id or ""):
            return mapped
    return ""


def entity_from_azure_row(row: Any) -> tuple[str, str]:
    """Return (entity_id, kind) for one Azure doc."""
    data = _as_dict(row)
    meta = _metadata(data)
    doc_id = str(data.get("id") or "")
    kind = classify_azure_kind(str(data.get("content_type") or ""), doc_id)
    key_order = {
        "meeting": ("event_id", "eventId", "entityId"),
        "contract": ("projectCMId", "ProjectCMId", "entityId"),
        "document": ("documentId", "DocumentId", "entityId"),
        "incident": ("incidentId", "IncidentId", "entityId"),
        "checklist": ("submissionId", "SubmissionId", "entityId"),
    }
    keys = key_order.get(kind) or (
        "event_id",
        "eventId",
        "entityId",
        "projectCMId",
        "documentId",
        "incidentId",
        "submissionId",
    )
    for key in keys:
        value = meta.get(key, data.get(key))
        if value is None or value == "":
            continue
        text = str(value).strip()
        if text and text != "0":
            return text, kind or "meeting"
    for pattern, mapped in _DOC_ID_KIND_RE:
        match = pattern.search(doc_id)
        if match and match.group(1) != "0":
            return match.group(1), kind or mapped
    match = _DOC_ID_EVENT_RE.search(doc_id)
    if match and match.group(1) != "0":
        return match.group(1), kind or "meeting"
    return "", kind


def ids_from_azure_rows(rows: list[Any]) -> set[str]:
    """Pull SPACE entity ids from Azure docs (event_id preferred over agenda PK)."""
    ids: set[str] = set()
    for row in rows:
        eid, _kind = entity_from_azure_row(row)
        if eid:
            ids.add(eid)
    return ids


def _ids_from_rows(rows: list[Any]) -> set[str]:
    return ids_from_azure_rows(rows)


def _merge_azure_rows(*lists: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for lst in lists:
        for row in lst or []:
            data = _as_dict(row)
            rid = str(data.get("id") or "")
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            merged.append(data)
    return merged


def _poc_hybrid_rows(
    query: str,
    content_type: str,
    top_k: int,
    *,
    embed_from: str = "",
) -> list[dict[str, Any]]:
    """POC hybrid_search core: semantic + BM25, plus embedding vector when ready."""
    from app.search.indexer import VECTOR_FIELD as INDEX_VECTOR_FIELD
    from app.search.indexer import get_search_client

    client = get_search_client(_index_name())
    if not client:
        return []

    fetch_n = max(min(top_k, 40), 8)
    filter_expr = CONTENT_TYPE_FILTER.get(content_type)
    embed_source = (embed_from or query).strip()
    should_embed = embed_source.endswith("?") or len(embed_source.split()) >= 5

    vector = None
    if should_embed:
        try:
            from app.search.embeddings import embed_text

            vector = embed_text(embed_source)
        except Exception:
            vector = None

    def run_search(search_text: str, use_semantic: bool, vec: Any) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "search_text": search_text,
            "top": fetch_n,
            "select": ["id", "title", "content", "content_type", "metadata"],
        }
        if filter_expr:
            kwargs["filter"] = filter_expr
        if use_semantic:
            kwargs["query_type"] = "semantic"
            kwargs["semantic_configuration_name"] = "default"
            kwargs["query_caption"] = "extractive"
        if vec:
            from azure.search.documents.models import VectorizedQuery

            kwargs["vector_queries"] = [
                VectorizedQuery(
                    vector=vec,
                    k_nearest_neighbors=max(fetch_n, 10),
                    fields=INDEX_VECTOR_FIELD,
                )
            ]
        try:
            return [_as_dict(r) for r in client.search(**kwargs)]
        except Exception:
            if use_semantic and kwargs.pop("query_caption", None):
                return [_as_dict(r) for r in client.search(**kwargs)]
            raise

    semantic_items: list[dict[str, Any]] = []
    keyword_items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="space-azure") as pool:
        f_sem = pool.submit(run_search, query, True, vector)
        f_kw = pool.submit(run_search, query, False, vector)
        try:
            semantic_items = f_sem.result(timeout=8)
        except Exception:
            log.warning("azure semantic search failed", extra={"errorCode": "azure_semantic_failed"})
        try:
            keyword_items = f_kw.result(timeout=8)
        except Exception:
            log.warning("azure keyword search failed", extra={"errorCode": "azure_keyword_failed"})

    merged = _merge_azure_rows(semantic_items, keyword_items)
    if merged:
        return merged
    try:
        return run_search(query, False, vector)
    except Exception:
        return []


def _rest_rows(query: str, content_type: str, top_k: int) -> list[Any]:
    endpoint = (settings.AZURE_SEARCH_ENDPOINT or "").rstrip("/")
    index = _index_name()
    if not endpoint or not index:
        return []
    url = (
        f"{endpoint}/indexes/{index}/docs/search"
        f"?api-version={settings.SPACE_AZURE_API_VERSION}"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": settings.AZURE_SEARCH_KEY or "",
    }

    def post(body: dict[str, Any]) -> httpx.Response:
        with httpx.Client(timeout=4.0) as client:
            return client.post(url, json=body, headers=headers)

    response = post(_keyword_only_body(query, content_type, top_k))
    if response.status_code >= 400:
        return []
    response.raise_for_status()
    return response.json().get("value") or []


def _compact_search_query(query: str) -> str:
    """Drop question filler so BM25 can match topic words like crane."""
    stop = {
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
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "for",
        "to",
        "my",
        "please",
        "about",
        "any",
        "all",
        "mention",
        "mentions",
        "mentioned",
        "meetings",
        "meeting",
        "events",
        "event",
        "contracts",
        "contract",
        "cms",
        "documents",
        "document",
        "docs",
        "dms",
        "incidents",
        "incident",
        "checklists",
        "checklist",
        "chkwp",
    }
    tokens = re.findall(r"[a-z0-9]+", query.strip().rstrip("?").lower())
    kept = [token for token in tokens if token not in stop and len(token) > 1]
    return " ".join(kept)


def _caption_text(data: dict[str, Any]) -> str:
    caps = data.get("@search.captions")
    if not caps:
        return ""
    parts: list[str] = []
    for cap in caps:
        text = ""
        if isinstance(cap, dict):
            text = str(cap.get("text") or cap.get("highlights") or "")
        else:
            text = str(getattr(cap, "text", None) or getattr(cap, "highlights", None) or "")
        if text.strip():
            parts.append(text.strip())
    return " ".join(parts)


def _row_haystack(data: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            str(data.get("title") or ""),
            str(data.get("content") or ""),
            _caption_text(data),
        )
        if part
    ).lower()


def row_matches_terms(data: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return True
    hay = _row_haystack(data)
    return all(term in hay for term in terms)


def _row_passage(data: dict[str, Any], terms: list[str]) -> str:
    caption = _caption_text(data)
    content = str(data.get("content") or "")
    title = str(data.get("title") or "")
    blob = caption or content or title
    if not blob:
        return ""
    lower = blob.lower()
    idx = -1
    for term in terms:
        found = lower.find(term)
        if found >= 0:
            idx = found
            break
    if idx < 0:
        return blob[:280]
    start = max(idx - 80, 0)
    return blob[start : start + 280].strip()


def discover_space_docs(query: str, content_type: str, top_k: int) -> list[dict[str, Any]]:
    """POC retrieval: hybrid search on topic words, keep docs that actually mention them."""
    if not is_azure_discovery_enabled() or not query.strip():
        return []
    if not _index_name():
        return []

    compact = _compact_search_query(query)
    search_text = compact or query.strip()
    try:
        keyword_rows = _rest_rows(search_text, content_type, top_k)
        # Semantic/vector neighbors are not matches when the topic word is absent.
        if compact and not keyword_rows:
            log.info(
                "azure discovery complete ids=none count=0 rows=0 kept=0 compact=yes keyword_miss=yes content_type=%s",
                content_type or "all",
            )
            return []
        rows = _poc_hybrid_rows(search_text, content_type, top_k, embed_from=query)
        if not rows:
            rows = keyword_rows
        if not rows and compact and compact.lower() != query.strip().lower():
            rows = _poc_hybrid_rows(compact, content_type, top_k, embed_from=query)
            if not rows:
                rows = _rest_rows(compact, content_type, top_k)
    except Exception:
        log.warning(
            "azure discovery skipped",
            extra={"content_type": content_type or "all", "errorCode": "azure_discovery_failed"},
        )
        return []

    terms = compact.split() if compact else []
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    kept_rows = 0
    for row in rows:
        data = _as_dict(row)
        if terms and not row_matches_terms(data, terms):
            continue
        kept_rows += 1
        eid, kind = entity_from_azure_row(data)
        if not eid:
            continue
        kind = kind or classify_azure_kind(str(data.get("content_type") or ""), str(data.get("id") or "")) or "meeting"
        seen_key = f"{kind}:{eid}"
        if seen_key in seen:
            continue
        seen.add(seen_key)
        docs.append(
            {
                "entity_id": eid,
                "kind": kind,
                "title": str(data.get("title") or ""),
                "snippet": _row_passage(data, terms)[:280],
                "content_type": str(data.get("content_type") or ""),
                "score": float(data.get("@search.score") or 0),
            }
        )

    sample = ",".join(str(_as_dict(row).get("id") or "")[:40] for row in rows[:3]) or "none"
    id_preview = ",".join(d["entity_id"] for d in docs[:16]) or "none"
    log.info(
        "azure discovery complete ids=%s count=%s rows=%s kept=%s sample=%s compact=%s content_type=%s",
        id_preview,
        len(docs),
        len(rows),
        kept_rows,
        sample,
        "yes" if compact else "no",
        content_type or "all",
    )
    return docs


def discover_entity_ids(query: str, content_type: str, top_k: int) -> set[str]:
    """Return entity ids from Azure hybrid search. Empty set on any failure."""
    return {doc["entity_id"] for doc in discover_space_docs(query, content_type, top_k) if doc.get("entity_id")}


def boost_discovered_hits(hits: list, discovered_ids: set[str], bonus: float = 0.15):
    """Prefer Azure-discovered ids without dropping API-only rows (index lag)."""
    if not discovered_ids:
        return hits
    boosted = []
    for hit in hits:
        score = hit.score or 0
        entity_id = str((hit.metadata or {}).get("entityId") or hit.id)
        if entity_id in discovered_ids:
            hit.score = score + bonus
        boosted.append(hit)
    return sorted(boosted, key=lambda row: (-(row.score or 0), row.title.lower()))
