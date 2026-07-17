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


def _normalize_doc_name(name: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "", (name or "").lower())


def _lookup_document_by_title(db: Session, title: str):
    from app.models.document import Document

    clean = (title or "").strip()
    if not clean:
        return None
    doc = db.query(Document).filter(Document.name == clean).first()
    if doc:
        return doc
    key = _normalize_doc_name(clean)
    if not key:
        return None
    for row in db.query(Document).all():
        if _normalize_doc_name(row.name) == key:
            return row
    return None


def _attach_document_file_identity(db: Session, item: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure blob search hits carry a stable document id for file download/view."""
    if item.get("content_type") != "document":
        return item

    doc_id = _document_id_from_hit(item)
    meta = dict(item.get("metadata") or {})
    patched = dict(item)

    if doc_id is None:
        row = _lookup_document_by_title(db, item.get("title", ""))
        if row is None:
            file_url = meta.get("file_url") or item.get("url") or ""
            if isinstance(file_url, str) and file_url:
                row = _lookup_document_by_title(db, file_url.split("/")[-1].split("?")[0])
        if row is not None:
            doc_id = row.id
            meta.setdefault("doc_id", row.id)
            meta.setdefault("file_type", row.file_type)
            meta.setdefault("file_url", row.file_url)
            patched["title"] = row.name

    if doc_id is not None:
        patched["id"] = f"document-{doc_id}"
        patched["url"] = f"/documents?docId={doc_id}"
        meta["doc_id"] = doc_id
        patched["metadata"] = meta

    return patched


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
        {
            d.id: d
            for d in db.query(Document).filter(Document.id.in_(doc_ids_needed)).all()
        }
        if doc_ids_needed
        else {}
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
                    "file_url": row.file_url,
                    "preview_url": getattr(row, "preview_url", None),
                    "sheet_notes": row.sheet_notes,
                }
            )
            inv_raw = getattr(row, "object_inventory", None)
            if inv_raw:
                try:
                    import json as _json

                    meta["object_inventory"] = _json.loads(inv_raw)
                except Exception:
                    meta["object_inventory"] = inv_raw
            intel_raw = getattr(row, "sheet_intel", None)
            if intel_raw:
                try:
                    import json as _json

                    meta["sheet_intel"] = _json.loads(intel_raw)
                except Exception:
                    meta["sheet_intel"] = intel_raw
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
            row = doc_ids.get(doc_id) if doc_id is not None else None
            meta = _parse_metadata(item.get("metadata"))
            if row is not None:
                meta.update(
                    {
                        "doc_id": row.id,
                        "file_type": row.file_type,
                        "file_url": row.file_url,
                        "body_text": getattr(row, "body_text", None),
                    }
                )
                body = (getattr(row, "body_text", None) or "").strip()
                patched = dict(item)
                patched["id"] = f"document-{row.id}"
                patched["title"] = row.name
                patched["url"] = f"/documents?docId={row.id}"
                if body and meta.get("content_source") != "blob_rag":
                    meta["content_source"] = meta.get("content_source") or "document_body_text"
                    meta["source"] = meta.get("source") or "document_body_text"
                    meta["blob_chunk"] = meta.get("blob_chunk") or body[:3500]
                    patched["snippet"] = (meta.get("blob_chunk") or body)[:500]
                patched["metadata"] = meta
                enriched.append(patched)
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
            enriched.append(_attach_document_file_identity(db, item))
            continue
        sql_meta = fresh.get("metadata") or {}
        patched = dict(item)
        patched["metadata"] = {**sql_meta, **meta}
        patched["title"] = fresh.get("title", item.get("title", ""))
        if from_blob and blob_snippet:
            patched["snippet"] = blob_snippet
            patched["metadata"] = {**sql_meta, **meta, "content_source": "blob_rag", "blob_chunk": meta.get("blob_chunk")}
        else:
            body = (sql_meta.get("body_text") or fresh.get("content") or "")
            patched["snippet"] = body[:500] if body else (fresh.get("content") or "")[:220]
            patched["metadata"] = {**sql_meta, **meta}
            if sql_meta.get("body_text") and not patched["metadata"].get("blob_chunk"):
                patched["metadata"]["body_text"] = sql_meta.get("body_text")
                patched["metadata"]["content_source"] = "document_body_text"
        enriched.append(_attach_document_file_identity(db, patched))
    return [_attach_document_file_identity(db, item) if item.get("content_type") == "document" else item for item in enriched]
