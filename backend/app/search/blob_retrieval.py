"""
Search document file content from the Azure Blob RAG index.

The SQL index (buildtrack-index) holds document metadata.
The RAG index (rag-*) holds extracted text chunks from blob files.
Global search merges both.
"""
from __future__ import annotations

import base64
import logging
import re
import time
import urllib.parse
from threading import Lock
from typing import Any, Optional

from app.core.config import settings
from app.search import index_reader
from app.search.query_planner import QueryMode, QueryPlan

logger = logging.getLogger(__name__)

BLOB_VECTOR_FIELD = "text_vector"
_BLOB_SELECT = ["chunk_id", "parent_id", "chunk", "title"]
_UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_",
    re.IGNORECASE,
)
_FILENAME_KEY = re.compile(r"[\s_\-]+")

_blob_index_name: Optional[str] = None
_semantic_config_name: Optional[str] = None
_file_url_index: Optional[dict[str, dict[str, Any]]] = None
_file_url_index_at: float = 0
# Rebuilding costs two 500-document index reads. The mapping only changes when
# the indexer picks up new files, which happens on a 15-minute schedule.
_FILE_URL_INDEX_TTL = 600
_file_url_index_lock = Lock()


def _normalize_blob_url(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url.strip())
    path = urllib.parse.unquote(parsed.path or "").lower().rstrip("/")
    return f"{parsed.netloc.lower()}{path}"


def decode_parent_blob_url(parent_id: str) -> str:
    if not parent_id:
        return ""
    if parent_id.startswith("http://") or parent_id.startswith("https://"):
        return parent_id
    padded = parent_id + "=" * (-len(parent_id) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8")
    except Exception:
        try:
            return base64.b64decode(padded).decode("utf-8")
        except Exception:
            return ""


def _filename_key(name: str) -> str:
    if not name:
        return ""
    base = urllib.parse.unquote(name.split("/")[-1])
    base = _UUID_PREFIX.sub("", base)
    return _FILENAME_KEY.sub("", base.lower())


def parse_rag_filename(title: str) -> str:
    if not title:
        return "Document"
    name = _UUID_PREFIX.sub("", title)
    return name.replace("_", " ") if "_" in name and " " not in name else name


def resolve_blob_index_name() -> Optional[str]:
    global _blob_index_name
    if settings.AZURE_SEARCH_BLOB_INDEX:
        return settings.AZURE_SEARCH_BLOB_INDEX
    if _blob_index_name:
        return _blob_index_name
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexClient

        client = SearchIndexClient(
            settings.AZURE_SEARCH_ENDPOINT,
            AzureKeyCredential(settings.AZURE_SEARCH_KEY),
        )
        for idx in client.list_indexes():
            if "rag" in idx.name.lower():
                _blob_index_name = idx.name
                return _blob_index_name
    except Exception as exc:
        logger.warning("Could not discover blob RAG index: %s", exc)
    return None


def _resolve_semantic_config() -> Optional[str]:
    global _semantic_config_name
    if _semantic_config_name:
        return _semantic_config_name
    index_name = resolve_blob_index_name()
    if not index_name:
        return None
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexClient

        client = SearchIndexClient(
            settings.AZURE_SEARCH_ENDPOINT,
            AzureKeyCredential(settings.AZURE_SEARCH_KEY),
        )
        idx = client.get_index(index_name)
        sem = idx.semantic_search
        if sem and sem.configurations:
            _semantic_config_name = sem.configurations[0].name
            return _semantic_config_name
        if sem and sem.default_configuration_name:
            _semantic_config_name = sem.default_configuration_name
            return _semantic_config_name
    except Exception as exc:
        logger.debug("Blob semantic config lookup failed: %s", exc)
    return None


def get_blob_search_client():
    index_name = resolve_blob_index_name()
    if not index_name or not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient

        return SearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=index_name,
            credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY),
        )
    except Exception as exc:
        logger.error("Failed to create blob search client: %s", exc)
        return None


def _build_file_url_index() -> dict[str, dict[str, Any]]:
    global _file_url_index, _file_url_index_at
    now = time.time()
    if _file_url_index and now - _file_url_index_at < _FILE_URL_INDEX_TTL:
        return _file_url_index

    with _file_url_index_lock:
        now = time.time()
        if _file_url_index and now - _file_url_index_at < _FILE_URL_INDEX_TTL:
            return _file_url_index
        return _load_file_url_index(now)


def _load_file_url_index(now: float) -> dict[str, dict[str, Any]]:
    global _file_url_index, _file_url_index_at
    mapping: dict[str, dict[str, Any]] = {}
    try:
        for content_type in ("document", "drawing"):
            for doc in index_reader.list_indexed(content_type, top=500, use_cache=True):
                meta = doc.get("metadata") or {}
                file_url = meta.get("file_url") or ""
                key = _normalize_blob_url(file_url)
                if key:
                    mapping[key] = doc
                drawing_no = (meta.get("drawing_no") or "").strip()
                if drawing_no:
                    mapping[f"drawing_no:{drawing_no.lower()}"] = doc
                for name in (
                    doc.get("title"),
                    file_url.split("/")[-1] if file_url else "",
                    drawing_no,
                ):
                    fkey = _filename_key(name or "")
                    if fkey:
                        mapping[f"name:{fkey}"] = doc
    except Exception as exc:
        logger.debug("File URL index build failed: %s", exc)

    _file_url_index = mapping
    _file_url_index_at = now
    return mapping


def should_search_blob_content(
    plan: QueryPlan,
    filter_type: Optional[str],
    query: str = "",
) -> bool:
    if not resolve_blob_index_name():
        return False
    if plan.mode == QueryMode.WORKFORCE:
        return False
    if plan.mode in (QueryMode.FILTER, QueryMode.LIST_ALL):
        return False
    if filter_type in ("projects", "tasks", "team"):
        return False
    # Count/layout on drawings — vision reads the image; blob crawl is redundant here.
    from app.search.query_intel import (
        is_drawing_count_query,
        is_drawing_vision_first_query,
        is_file_content_query,
        is_asset_inventory_query,
        is_question,
    )

    if is_drawing_count_query(query) or is_drawing_vision_first_query(query):
        return False
    # Equipment / vendor / material questions → Azure SQL assets index, not blob RAG.
    if is_asset_inventory_query(query):
        return False
    # Always try blob/RAG for document-content questions and general questions
    # (body_text injection still helps when RAG is empty).
    from app.search.query_intel import is_workforce_people_query

    if is_workforce_people_query(query):
        return False
    if is_file_content_query(query):
        return True
    if is_question(query) and filter_type in (None, "", "all", "documents"):
        return True
    return False


def _inject_drawing_sheet_notes(item: dict[str, Any]) -> dict[str, Any]:
    """Attach sheet_notes as crawl text when no blob/RAG chunk is available yet."""
    meta = dict(item.get("metadata") or {})
    if meta.get("blob_chunk") and meta.get("content_source") == "blob_rag":
        return item
    notes = (meta.get("sheet_notes") or "").strip()
    if not notes and not meta.get("blob_chunk"):
        return item
    patched = dict(item)
    text = (meta.get("blob_chunk") or notes).strip()
    meta["blob_chunk"] = text[:3500]
    if meta.get("content_source") != "blob_rag":
        meta["content_source"] = "drawing_sheet_notes"
        meta["source"] = "drawing_sheet_notes"
    patched["metadata"] = meta
    patched["snippet"] = text[:500]
    return patched


def _inject_document_body_text(item: dict[str, Any]) -> dict[str, Any]:
    """Attach extracted body_text when no blob/RAG chunk is available yet."""
    meta = dict(item.get("metadata") or {})
    if meta.get("blob_chunk") and meta.get("content_source") == "blob_rag":
        return item
    body = (meta.get("body_text") or "").strip()
    if not body and not meta.get("blob_chunk"):
        return item
    patched = dict(item)
    text = (meta.get("blob_chunk") or body).strip()
    meta["blob_chunk"] = text[:3500]
    if meta.get("content_source") != "blob_rag":
        meta["content_source"] = "document_body_text"
        meta["source"] = "document_body_text"
    patched["metadata"] = meta
    patched["snippet"] = text[:500]
    return patched


def enrich_drawing_hits_with_crawl_text(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure drawing/document hits carry crawlable text from notes/body or blob chunks."""
    out: list[dict[str, Any]] = []
    for h in hits:
        ctype = h.get("content_type")
        if ctype == "drawing":
            out.append(_inject_drawing_sheet_notes(h))
        elif ctype == "document":
            out.append(_inject_document_body_text(h))
        else:
            out.append(h)
    return out


def _row_to_hit(row: dict[str, Any]) -> dict[str, Any]:
    parent_id = row.get("parent_id") or ""
    blob_url = decode_parent_blob_url(parent_id)
    rag_title = row.get("title") or ""
    chunk = (row.get("chunk") or "").strip()
    chunk_id = row.get("chunk_id") or row.get("id") or ""

    sql_doc = _build_file_url_index().get(_normalize_blob_url(blob_url))
    if sql_doc is None:
        sql_doc = _build_file_url_index().get(f"name:{_filename_key(rag_title)}")
    if sql_doc is None and blob_url:
        sql_doc = _build_file_url_index().get(f"name:{_filename_key(blob_url)}")
    if sql_doc is None:
        from app.search.query_intel import extract_drawing_no

        drawing_no = extract_drawing_no(rag_title) or extract_drawing_no(blob_url)
        if drawing_no:
            sql_doc = _build_file_url_index().get(f"drawing_no:{drawing_no.lower()}")
    meta: dict[str, Any] = {
        "source": "blob_rag",
        "content_source": "blob_rag",
        "file_url": blob_url,
        "chunk_id": chunk_id,
    }
    if chunk:
        meta["blob_chunk"] = chunk[:3500]

    if sql_doc:
        sql_meta = dict(sql_doc.get("metadata") or {})
        meta.update(sql_meta)
        meta["source"] = "blob_rag"
        meta["content_source"] = "blob_rag"
        meta["chunk_id"] = chunk_id
        if chunk:
            meta["blob_chunk"] = chunk[:3500]
        ctype = sql_doc.get("content_type") or "document"
        doc_id = sql_meta.get("doc_id")
        drawing_id = sql_meta.get("drawing_id")
        if ctype == "drawing" and drawing_id is not None:
            item_id = sql_doc.get("id") or f"drawing-{drawing_id}"
            url = sql_doc.get("url") or f"/drawings?drawingId={drawing_id}"
        else:
            item_id = sql_doc.get("id") or (f"document-{doc_id}" if doc_id else f"blob-{chunk_id}")
            url = sql_doc.get("url") or (f"/documents?docId={doc_id}" if doc_id else blob_url)
        title = sql_doc.get("title") or parse_rag_filename(rag_title)
    else:
        item_id = f"blob-{chunk_id}" if chunk_id else f"blob-{hash(blob_url)}"
        title = parse_rag_filename(rag_title)
        url = blob_url or "/documents"
        ctype = "document"

    snippet = chunk[:400] if chunk else title[:220]
    return {
        "id": item_id,
        "title": title,
        "snippet": snippet,
        "content_type": ctype if sql_doc else "document",
        "url": url,
        "metadata": meta,
        "score": row.get("@search.score", 0),
        "_parent_id": parent_id,
        "_blob_url": blob_url,
    }


_QUERY_STOP = {
    "what", "which", "where", "when", "how", "why", "who", "the", "and", "for",
    "are", "was", "were", "mentioned", "mention", "document", "report", "file",
    "project", "bridge", "from", "that", "this", "with", "about",
}


def _chunk_query_relevance(chunk: str, query: str) -> float:
    if not chunk:
        return 0.0
    text = chunk.lower()
    words = [
        w for w in re.findall(r"[a-z0-9]+", query.lower())
        if len(w) > 3 and w not in _QUERY_STOP
    ]
    score = 0.0
    if words:
        score = sum(1 for w in words if w in text) / len(words)
    if re.search(r"\bsafety|hse|ppe\b", query, re.IGNORECASE):
        if "hse metric" in text or "health, safety" in text or "ppe compliance" in text:
            score += 1.5
        if "toolbox talks" in text or "near miss" in text:
            score += 0.8
    return score


def _file_key(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    rid = str(hit.get("id", ""))
    if rid.startswith("document-") or rid.startswith("drawing-"):
        return rid
    drawing_no = (meta.get("drawing_no") or "").strip()
    if drawing_no:
        return f"drawing_no:{drawing_no.lower()}"
    return (
        _filename_key(meta.get("file_url") or hit.get("title", ""))
        or hit.get("_blob_url")
        or hit.get("_parent_id")
        or rid
    )


def _merge_file_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine multiple passages from the same file into one richer hit."""
    base = dict(chunks[0])
    seen: set[str] = set()
    parts: list[str] = []
    for hit in chunks:
        text = ((hit.get("metadata") or {}).get("blob_chunk") or hit.get("snippet") or "").strip()
        if not text:
            continue
        key = text[:120]
        if key in seen:
            continue
        seen.add(key)
        parts.append(text)

    combined = "\n\n".join(parts)
    meta = dict(base.get("metadata") or {})
    meta["blob_chunk"] = combined[:3500]
    meta["content_source"] = "blob_rag"
    meta["source"] = "blob_rag"
    meta["chunk_count"] = len(parts)
    base["metadata"] = meta
    base["snippet"] = combined[:500]
    base["score"] = max(float(h.get("score") or 0) for h in chunks)
    return base


def _collapse_chunks(hits: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    """Keep the best chunk per blob file — prefer query-relevant passages."""
    best: dict[str, dict[str, Any]] = {}
    for hit in hits:
        key = _file_key(hit)
        if not key:
            continue
        chunk_text = (hit.get("metadata") or {}).get("blob_chunk") or hit.get("snippet") or ""
        relevance = _chunk_query_relevance(chunk_text, query)
        combined = float(hit.get("score") or 0) + relevance * 20.0
        prev = best.get(key)
        if prev is None or combined > prev.get("_rank_score", 0):
            hit["_rank_score"] = combined
            best[key] = hit
    return list(best.values())


def _collapse_chunks_multi(
    hits: list[dict[str, Any]], query: str, *, max_per_file: int = 4
) -> list[dict[str, Any]]:
    """Keep several relevant chunks per file for comprehensive content answers."""
    if re.search(r"\bsafety|hse|ppe\b", query, re.IGNORECASE):
        max_per_file = max(max_per_file, 5)

    by_file: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        key = _file_key(hit)
        if not key:
            continue
        chunk_text = (hit.get("metadata") or {}).get("blob_chunk") or hit.get("snippet") or ""
        relevance = _chunk_query_relevance(chunk_text, query)
        hit["_rank_score"] = float(hit.get("score") or 0) + relevance * 20.0
        by_file.setdefault(key, []).append(hit)

    merged: list[dict[str, Any]] = []
    for file_hits in by_file.values():
        ranked = sorted(file_hits, key=lambda h: h.get("_rank_score", 0), reverse=True)
        top = ranked[:max_per_file]
        if re.search(r"\bsafety|hse|ppe\b", query, re.IGNORECASE):
            for hit in ranked:
                text = ((hit.get("metadata") or {}).get("blob_chunk") or hit.get("snippet") or "").lower()
                if "hse metric" in text or "health, safety & environment" in text:
                    if hit not in top:
                        top = [hit, *top[: max_per_file - 1]]
                    break
        merged.append(_merge_file_chunks(top) if len(top) > 1 else top[0])
    merged.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
    return merged


def _supplemental_search_queries(query: str) -> list[str]:
    """Extra blob searches so list-style questions pull the right document section."""
    q = query.lower()
    extras: list[str] = []
    if re.search(r"\bsafety|hse|ppe|incident|hazard\b", q):
        extras.append(
            "Health Safety Environment HSE PPE compliance toolbox talks inspections near miss drills helmets harnesses"
        )
    if re.search(r"\bbudget|cost|expenditure|financial\b", q):
        extras.append("budget utilization expenditure cost financial variance")
    if re.search(r"\bschedule|timeline|milestone|progress\b", q):
        extras.append("schedule milestone progress plan quarter activities")
    if re.search(r"\bpile|piling|diameter|foundation|bored|truss|span|incomer|hvac\b", q):
        extras.append(
            "bored cast-in-situ pile diameter spacing foundation layout piling notes grid "
            "truss span member size electrical incomer HVAC duct"
        )
    from app.search.query_intel import extract_drawing_no

    drawing_no = extract_drawing_no(query)
    if drawing_no:
        extras.append(f"{drawing_no} sheet content general notes specifications schedule")
    return extras


def fetch_raw_chunks_for_document(title: str, search_text: str, *, top: int = 20) -> list[str]:
    """Return raw blob chunk texts for one file (no collapse — keeps all passages)."""
    client = get_blob_search_client()
    if not client:
        return []
    title_key = _filename_key(title)
    if not title_key:
        return []
    chunks: list[str] = []
    seen: set[str] = set()
    for row in client.search(search_text=search_text, top=top, select=_BLOB_SELECT):
        if _filename_key(row.get("title") or "") != title_key:
            continue
        text = (row.get("chunk") or "").strip()
        if not text or text[:100] in seen:
            continue
        seen.add(text[:100])
        chunks.append(text)
    return chunks


def search_blob_content(
    query: str,
    *,
    search_text: Optional[str] = None,
    top_k: int = 10,
    vector: Optional[list[float]] = None,
    use_semantic: bool = True,
    multi_chunk: bool = False,
) -> list[dict[str, Any]]:
    client = get_blob_search_client()
    if not client:
        return []

    text = (search_text or query).strip()
    if not text:
        return []

    kwargs: dict[str, Any] = {
        "search_text": text,
        "top": min(max(top_k * 3, 20), 40) if multi_chunk else min(max(top_k * 2, 12), 30),
        "select": _BLOB_SELECT,
    }

    if use_semantic:
        sem = _resolve_semantic_config()
        if sem:
            kwargs["query_type"] = "semantic"
            kwargs["semantic_configuration_name"] = sem

    if vector:
        try:
            from azure.search.documents.models import VectorizedQuery

            kwargs["vector_queries"] = [
                VectorizedQuery(
                    vector=vector,
                    k_nearest_neighbors=kwargs["top"],
                    fields=BLOB_VECTOR_FIELD,
                )
            ]
        except Exception as exc:
            logger.debug("Blob vector query not attached: %s", exc)

    rows: list[dict[str, Any]] = []
    try:
        for row in client.search(**kwargs):
            rows.append(_row_to_hit(dict(row)))

        if multi_chunk:
            seen_chunks = {((h.get("metadata") or {}).get("chunk_id") or h.get("id")) for h in rows}
            for extra_q in _supplemental_search_queries(query):
                extra_kwargs = {**kwargs, "search_text": extra_q, "top": 15}
                for row in client.search(**extra_kwargs):
                    hit = _row_to_hit(dict(row))
                    cid = (hit.get("metadata") or {}).get("chunk_id") or hit.get("id")
                    if cid not in seen_chunks:
                        seen_chunks.add(cid)
                        rows.append(hit)
    except Exception as exc:
        logger.warning("Blob content search failed: %s", exc)
        if use_semantic:
            return search_blob_content(
                query,
                search_text=search_text,
                top_k=top_k,
                vector=vector,
                use_semantic=False,
                multi_chunk=multi_chunk,
            )
        return []

    collapsed = (
        _collapse_chunks_multi(rows, query)
        if multi_chunk
        else _collapse_chunks(rows, query)
    )
    for hit in collapsed:
        hit.pop("_parent_id", None)
        hit.pop("_blob_url", None)
        hit.pop("_rank_score", None)
    return collapsed


def merge_sql_and_blob_hits(
    sql_hits: list[dict[str, Any]],
    blob_hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge SQL metadata hits with blob content hits; prefer blob snippet when same file."""
    blob_by_doc_id: dict[str, dict[str, Any]] = {}
    blob_by_drawing_id: dict[str, dict[str, Any]] = {}
    blob_by_url: dict[str, dict[str, Any]] = {}
    blob_by_name: dict[str, dict[str, Any]] = {}
    blob_by_drawing_no: dict[str, dict[str, Any]] = {}
    for hit in blob_hits:
        meta = hit.get("metadata") or {}
        doc_id = meta.get("doc_id")
        if doc_id is not None:
            blob_by_doc_id[f"document-{doc_id}"] = hit
        # Sidecar / blob metadata may carry document_id instead of doc_id
        alt_doc_id = meta.get("document_id")
        if alt_doc_id is not None and f"document-{alt_doc_id}" not in blob_by_doc_id:
            blob_by_doc_id[f"document-{alt_doc_id}"] = hit
        drawing_id = meta.get("drawing_id")
        if drawing_id is not None:
            blob_by_drawing_id[f"drawing-{drawing_id}"] = hit
        drawing_no = (meta.get("drawing_no") or "").strip().lower()
        if drawing_no:
            blob_by_drawing_no[drawing_no] = hit
        url_key = _normalize_blob_url(meta.get("file_url") or "")
        if url_key:
            blob_by_url[url_key] = hit
        name_key = _filename_key(hit.get("title") or meta.get("file_url") or "")
        if name_key:
            blob_by_name[name_key] = hit

    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for item in sql_hits:
        rid = item.get("id", "")
        seen_ids.add(rid)
        ctype = item.get("content_type")
        if ctype not in ("document", "drawing"):
            merged.append(item)
            continue

        blob_match = None
        if ctype == "document":
            blob_match = blob_by_doc_id.get(rid)
        elif ctype == "drawing":
            blob_match = blob_by_drawing_id.get(rid)
            if blob_match is None:
                dno = (item.get("metadata") or {}).get("drawing_no", "").lower()
                if dno:
                    blob_match = blob_by_drawing_no.get(dno)

        if blob_match is None:
            meta = item.get("metadata") or {}
            blob_match = blob_by_url.get(_normalize_blob_url(meta.get("file_url") or ""))
        if blob_match is None:
            blob_match = blob_by_name.get(_filename_key(item.get("title") or ""))

        if blob_match:
            patched = dict(item)
            patched["snippet"] = blob_match.get("snippet") or patched.get("snippet", "")
            patched["score"] = max(item.get("score", 0), blob_match.get("score", 0))
            item_meta = item.get("metadata") or {}
            blob_meta = blob_match.get("metadata") or {}
            patched["metadata"] = {**item_meta, **blob_meta, "content_source": "blob_rag"}
            merged.append(patched)
        elif ctype == "drawing":
            merged.append(_inject_drawing_sheet_notes(item))
        elif ctype == "document":
            merged.append(_inject_document_body_text(item))
        else:
            merged.append(item)

    for hit in blob_hits:
        rid = hit.get("id", "")
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            merged.append(hit)

    return enrich_drawing_hits_with_crawl_text(merged)
