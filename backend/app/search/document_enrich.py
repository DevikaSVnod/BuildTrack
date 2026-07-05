"""Refresh search hits from SQL so stale Azure index rows are not shown."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.search.index_reader import get_indexed


def _drawing_id_from_hit(item: Dict[str, Any]) -> Optional[int]:
    rid = item.get("id", "")
    m = re.match(r"drawing-(\d+)", str(rid))
    if m:
        return int(m.group(1))
    meta = item.get("metadata") or {}
    did = meta.get("drawing_id")
    if did is not None:
        try:
            return int(did)
        except (TypeError, ValueError):
            return None
    return None


def _document_id_from_hit(item: Dict[str, Any]) -> Optional[int]:
    rid = item.get("id", "")
    m = re.match(r"document-(\d+)", str(rid))
    if m:
        return int(m.group(1))
    meta = item.get("metadata") or {}
    did = meta.get("doc_id")
    if did is not None:
        try:
            return int(did)
        except (TypeError, ValueError):
            return None
    return None


def _parse_metadata(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def enrich_document_results(db: Session, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop stale SQL-backed hits and refresh titles/snippets from live SQL rows."""
    from app.models.document import Document
    from app.models.operational import EngineeringDrawing

    drawing_ids_needed = {
        did
        for item in results
        if item.get("content_type") == "drawing"
        for did in [_drawing_id_from_hit(item)]
        if did is not None
    }
    doc_ids_needed = {
        did
        for item in results
        if item.get("content_type") == "document"
        for did in [_document_id_from_hit(item)]
        if did is not None
    }

    drawings = (
        {
            d.id: d
            for d in db.query(EngineeringDrawing)
            .filter(EngineeringDrawing.id.in_(drawing_ids_needed))
            .all()
        }
        if drawing_ids_needed
        else {}
    )
    doc_ids = (
        {d.id for d in db.query(Document.id).filter(Document.id.in_(doc_ids_needed)).all()}
        if doc_ids_needed
        else set()
    )

    enriched: List[Dict[str, Any]] = []
    for item in results:
        ctype = item.get("content_type")

        if ctype == "drawing":
            drawing_id = _drawing_id_from_hit(item)
            if drawing_id is None or drawing_id not in drawings:
                continue
            row = drawings[drawing_id]
            meta = _parse_metadata(item.get("metadata"))
            meta.update(
                {
                    "drawing_id": row.id,
                    "drawing_no": row.drawing_no,
                    "discipline": row.discipline,
                    "revision": row.revision,
                    "status": row.status,
                    "project": row.project_name,
                    "file_type": row.file_type,
                }
            )
            patched = dict(item)
            patched["id"] = f"drawing-{row.id}"
            patched["title"] = f"{row.drawing_no} – {row.title}"
            notes = (row.sheet_notes or "").strip()
            if notes and not meta.get("content_source") == "blob_rag":
                patched["snippet"] = notes[:220]
            patched["metadata"] = meta
            patched["url"] = "/drawings"
            enriched.append(patched)
            continue

        if ctype == "document":
            doc_id = _document_id_from_hit(item)
            if doc_id is not None and doc_id not in doc_ids:
                continue

        if ctype != "document":
            enriched.append(item)
            continue
        meta = item.get("metadata") or {}
        blob_snippet = item.get("snippet", "")
        from_blob = meta.get("content_source") == "blob_rag" or meta.get("source") == "blob_rag"

        rid = item.get("id", "")
        m = re.match(r"document-(\d+)", rid)
        if not m and isinstance(meta, dict):
            did = meta.get("doc_id")
            rid = f"document-{did}" if did is not None else rid
        fresh = get_indexed(rid) if rid else None
        if not fresh:
            enriched.append(item)
            continue
        sql_meta = fresh.get("metadata") or {}
        patched = dict(item)
        patched["metadata"] = {**sql_meta, **meta}
        patched["title"] = fresh.get("title", item.get("title", ""))
        if from_blob and blob_snippet:
            patched["snippet"] = blob_snippet
            patched["metadata"] = {**sql_meta, **meta, "content_source": "blob_rag", "blob_chunk": meta.get("blob_chunk")}
        else:
            patched["snippet"] = (fresh.get("content") or "")[:220]
            patched["metadata"] = {**sql_meta, **meta}
        enriched.append(patched)
    return enriched
