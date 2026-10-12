"""Index CMS / DMS / Incident / CHKWP rows into the SPACE Azure index.

Sync-time SQL only (same as Action → space-action-index). Live header search
still uses Azure hybrid + module APIs with the SPACE JWT.
Do not index Project / LMS / UM.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.space_databases import get_space_db_config, resolve_space_database_url
from app.search.indexer import index_documents
from app.search.space_indexer import space_index_name

log = logging.getLogger("space-module-indexer")

_MAX_ROWS = 25_000
_MAX_CONTENT = 8_000

# source_id, content_type, doc id prefix, metadata id key, SQL
_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "space-cms",
        "content_type": "contract",
        "id_prefix": "space-contract",
        "id_key": "projectCMId",
        "sql": (
            "SELECT TOP ({limit}) ProjectCMID, ProjectId, NameofContract, ContractNo, "
            "EmployerName, ContractorName "
            "FROM cms.[ProjectCM] WHERE ISNULL(IsActive, 1) = 1"
        ),
    },
    {
        "source_id": "space-dms",
        "content_type": "document",
        "id_prefix": "space-document",
        "id_key": "documentId",
        "database": "TEST_V1_SPACE_DMS",
        "sql": (
            "SELECT TOP ({limit}) DocumentId, DocumentNumber, Title, ContentInformation, "
            "MasterKeyword, CustomKeyword "
            "FROM dms.[Document] WHERE ISNULL(IsActive, 1) = 1 AND ISNULL(IsDeleted, 0) = 0"
        ),
    },
    {
        "source_id": "space-incident",
        "content_type": "incident",
        "id_prefix": "space-incident",
        "id_key": "incidentId",
        "sql": (
            "SELECT TOP ({limit}) IncidentId, IncidentNumber, Details, LocationDetails "
            "FROM incident.[Incident_Information] WHERE ISNULL(IsActive, 1) = 1"
        ),
    },
    {
        "source_id": "space-chkwp",
        "content_type": "checklist",
        "id_prefix": "space-checklist",
        "id_key": "submissionId",
        "sql": (
            "SELECT TOP ({limit}) SubmissionId, SubmissionNumber, LocationDetails "
            "FROM chkwp.[Submission] WHERE ISNULL(IsActive, 1) = 1"
        ),
    },
)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _engine_for(source_id: str, database: str | None = None):
    from scripts.setup_assets_db import create_mssql_engine

    cfg = get_space_db_config(source_id)
    if cfg is None:
        return None
    try:
        url = resolve_space_database_url(cfg)
        if database:
            url = url.set(database=database)
        # Pass the URL object — str(url) corrupts passwords that contain @.
        return create_mssql_engine(url)
    except Exception:
        log.warning("space module index skipped", extra={"source": source_id, "errorCode": "db_url_failed"})
        return None


def _row_id(row: dict[str, Any], spec: dict[str, Any]) -> str:
    key = spec["id_key"]
    mapping = {
        "projectCMId": ("ProjectCMID", "ProjectCMId"),
        "documentId": ("DocumentId",),
        "incidentId": ("IncidentId",),
        "submissionId": ("SubmissionId",),
    }
    for col in mapping.get(key, ()):
        value = row.get(col)
        if value is not None and str(value).strip() and str(value).strip() != "0":
            return str(int(value)) if isinstance(value, (int, float)) else str(value).strip()
    return ""


def _title_content(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    kind = spec["content_type"]
    if kind == "contract":
        title = _clean(row.get("NameofContract")) or _clean(row.get("ContractNo")) or "Contract"
        parts = [
            _clean(row.get("NameofContract")),
            f"Contract number: {_clean(row.get('ContractNo'))}",
            f"Employer: {_clean(row.get('EmployerName'))}",
            f"Contractor: {_clean(row.get('ContractorName'))}",
        ]
        return title, "\n".join(p for p in parts if p and not p.endswith(": "))
    if kind == "document":
        title = _clean(row.get("Title")) or _clean(row.get("DocumentNumber")) or "Document"
        parts = [
            title,
            f"Document number: {_clean(row.get('DocumentNumber'))}",
            _clean(row.get("MasterKeyword")),
            _clean(row.get("CustomKeyword")),
            _clean(row.get("ContentInformation"))[:_MAX_CONTENT],
        ]
        return title, "\n".join(p for p in parts if p and not p.endswith(": "))
    if kind == "incident":
        title = _clean(row.get("IncidentNumber")) or "Incident"
        parts = [
            title,
            _clean(row.get("Details")),
            _clean(row.get("LocationDetails")),
        ]
        return title, "\n".join(p for p in parts if p)
    title = _clean(row.get("SubmissionNumber")) or "Checklist"
    parts = [title, _clean(row.get("LocationDetails"))]
    return title, "\n".join(p for p in parts if p)


def _load_source(spec: dict[str, Any]) -> list[dict[str, Any]]:
    engine = _engine_for(spec["source_id"], spec.get("database"))
    if engine is None:
        return []
    Session = sessionmaker(bind=engine)
    db = Session()
    docs: list[dict[str, Any]] = []
    try:
        sql = spec["sql"].format(limit=_MAX_ROWS)
        rows = db.execute(text(sql)).mappings().all()
        for raw in rows:
            row = dict(raw)
            entity_id = _row_id(row, spec)
            if not entity_id:
                continue
            title, content = _title_content(row, spec)
            meta: dict[str, Any] = {
                spec["id_key"]: entity_id,
                "record_id": entity_id,
                "source_id": spec["source_id"],
                "table": spec["source_id"],
            }
            if spec["content_type"] == "contract":
                pid = row.get("ProjectId")
                if pid is not None:
                    meta["projectId"] = pid
                    meta["projectCMId"] = entity_id
            docs.append(
                {
                    "id": f"{spec['id_prefix']}-{entity_id}",
                    "title": title[:180],
                    "content": content[:_MAX_CONTENT],
                    "content_type": spec["content_type"],
                    "url": "",
                    "metadata": json.dumps(meta, ensure_ascii=False, default=str),
                }
            )
        log.info(
            "space module indexed source=%s docs=%s",
            spec["source_id"],
            len(docs),
        )
    except Exception:
        log.warning(
            "space module index failed",
            extra={"source": spec["source_id"], "errorCode": "module_index_failed"},
        )
        return []
    finally:
        db.close()
        engine.dispose()
    return docs


def load_space_module_search_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for spec in _SOURCES:
        docs.extend(_load_source(spec))
    return docs


def sync_space_modules_to_azure_search(*, embed: bool = True) -> dict[str, Any]:
    """Upload CMS/DMS/Incident/CHKWP docs into the same SPACE Azure index."""
    index = space_index_name()
    docs = load_space_module_search_docs()
    if not docs:
        return {
            "index": index,
            "documents_loaded": 0,
            "uploaded_ok": 0,
            "uploaded_failed": 0,
            "message": "No CMS/DMS/Incident/CHKWP rows indexed",
        }
    result = index_documents(docs, embed=embed, index_name=index)
    return {
        "index": index,
        "documents_loaded": len(docs),
        "uploaded_ok": result.get("ok", 0),
        "uploaded_failed": result.get("failed", 0),
        "message": f"Synced {result.get('ok', 0)} module docs into '{index}'",
    }
