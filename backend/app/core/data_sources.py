"""
Multi-database registry for Global Search.

Each configured source has its own SQL connection and Azure Search index.
When SEARCH_DATA_SOURCES is unset, sources are:
  1) primary DATABASE_URL + AZURE_SEARCH_INDEX
  2) ASSETS_DATABASE_URL (Azure SQL buildtrack_assets on same server)
  3) SPACE_DATABASE_URL Space Action (+ enabled sibling Space DBs e.g. Project)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataSource:
    id: str
    label: str
    database_url: str
    search_index: str = ""
    blob_index: Optional[str] = None
    enabled: bool = True
    # "azure" = hybrid Azure AI Search; "sql" = search_documents table in this DB
    retrieval_mode: str = "azure"


def assets_database_url() -> str:
    """Stable id string for the assets Azure SQL database (not used for login)."""
    return "azure-sql://buildtrack_assets"


def ensure_assets_database() -> str:
    """Ensure Azure SQL buildtrack_assets exists and is seeded. Returns DB name."""
    from scripts.setup_assets_db import setup

    return setup(force=False)


def _engine_kwargs(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
    common = {
        "pool_pre_ping": True,
        "pool_size": 3,
        "max_overflow": 5,
        "pool_recycle": 1800,
        "pool_timeout": 15,
    }
    if url.startswith("mssql"):
        return {**common, "connect_args": {"timeout": 45}}
    return common


def _create_engine_for_source(source: DataSource) -> Engine:
    """Build engines from URL objects / env strings — never str(URL) (breaks on # in passwords)."""
    from scripts.setup_assets_db import create_mssql_engine, resolve_assets_database_url

    if source.id == "assets" or "buildtrack_assets" in (source.database_url or ""):
        return create_mssql_engine(resolve_assets_database_url())
    from app.core.space_databases import get_space_db_config, resolve_space_database_url

    space_cfg = get_space_db_config(source.id)
    if space_cfg is not None:
        return create_mssql_engine(resolve_space_database_url(space_cfg))
    if source.id == "buildtrack" or (
        source.database_url.startswith("mssql") and "buildtrack" in source.database_url
    ):
        # Use raw env string (percent-encoded password) — safe to make_url once.
        return create_mssql_engine(settings.DATABASE_URL)
    if source.database_url.startswith("mssql"):
        return create_mssql_engine(source.database_url)
    return create_engine(source.database_url, **_engine_kwargs(source.database_url))


def _parse_sources_json(raw: str) -> list[DataSource]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Invalid SEARCH_DATA_SOURCES JSON: %s", exc)
        return []

    if not isinstance(payload, list):
        logger.error("SEARCH_DATA_SOURCES must be a JSON array")
        return []

    sources: list[DataSource] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        url = str(item.get("database_url") or item.get("DATABASE_URL") or "").strip()
        if not sid or not url:
            logger.warning("Skipping data source missing id/database_url: %s", item)
            continue
        mode = str(item.get("retrieval_mode") or "azure").strip().lower()
        if mode not in ("azure", "sql"):
            mode = "azure"
        index = str(
            item.get("search_index")
            or item.get("AZURE_SEARCH_INDEX")
            or ("" if mode == "sql" else settings.AZURE_SEARCH_INDEX)
        ).strip()
        sources.append(
            DataSource(
                id=sid,
                label=str(item.get("label") or sid).strip(),
                database_url=url,
                search_index=index,
                blob_index=(
                    str(item["blob_index"]).strip()
                    if item.get("blob_index")
                    else None
                ),
                enabled=bool(item.get("enabled", True)),
                retrieval_mode=mode,
            )
        )
    return sources


def _default_source() -> DataSource:
    return DataSource(
        id="buildtrack",
        label="BuildTrack",
        database_url=settings.DATABASE_URL,
        search_index=settings.AZURE_SEARCH_INDEX,
        blob_index=settings.AZURE_SEARCH_BLOB_INDEX,
        enabled=bool(settings.SEARCH_ENABLE_BUILDTRACK),
        retrieval_mode="azure",
    )


def _assets_source() -> Optional[DataSource]:
    """Second source: Azure SQL buildtrack_assets → Azure AI Search assets index."""
    if not settings.DATABASE_URL.startswith("mssql") and not settings.ASSETS_DATABASE_URL:
        return None
    try:
        url = assets_database_url()
    except Exception as exc:
        logger.warning("Could not resolve assets database URL: %s", exc)
        return None

    azure_ready = bool(settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_KEY)
    return DataSource(
        id="assets",
        label="Site Assets & Procurement",
        database_url=url,
        search_index=(
            (settings.AZURE_SEARCH_ASSETS_INDEX or "buildtrack-assets-index")
            if azure_ready
            else ""
        ),
        blob_index=None,
        enabled=bool(settings.SEARCH_ENABLE_ASSETS),
        retrieval_mode="azure" if azure_ready else "sql",
    )


def _space_source() -> Optional[DataSource]:
    """Optional Space Action SQL → Azure AI Search space-action-index."""
    if not (settings.SPACE_DATABASE_URL or "").strip():
        return None
    azure_ready = bool(settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_KEY)
    return DataSource(
        id="space",
        label="Space Action",
        database_url=settings.SPACE_DATABASE_URL or "",
        search_index=(
            (settings.AZURE_SEARCH_SPACE_INDEX or "space-action-index")
            if azure_ready
            else ""
        ),
        blob_index=None,
        enabled=bool(settings.SEARCH_ENABLE_SPACE),
        retrieval_mode="azure" if azure_ready else "sql",
    )


def _sibling_space_sources() -> list[DataSource]:
    """Schema-first Space DBs other than Action (Project, Common, UM, …)."""
    if not (settings.SPACE_DATABASE_URL or "").strip():
        return []
    from app.core.space_databases import (
        is_space_db_enabled,
        list_known_space_db_configs,
        resolve_space_database_url,
    )

    out: list[DataSource] = []
    for cfg in list_known_space_db_configs():
        if cfg.source_id == "space":
            continue
        try:
            resolve_space_database_url(cfg)
        except Exception as exc:
            logger.warning("Could not resolve %s URL: %s", cfg.source_id, exc)
            continue
        out.append(
            DataSource(
                id=cfg.source_id,
                label=cfg.label,
                database_url=f"space://{cfg.database_name}",
                search_index="",  # schema-SQL only unless has_row_index later
                blob_index=None,
                enabled=is_space_db_enabled(cfg),
                retrieval_mode="azure",  # connector special-cases Space sources
            )
        )
    return out


@lru_cache(maxsize=1)
def list_configured_sources() -> tuple[DataSource, ...]:
    raw = (settings.SEARCH_DATA_SOURCES or "").strip()
    if raw:
        parsed = _parse_sources_json(raw)
        if parsed:
            return tuple(parsed)
        logger.warning(
            "SEARCH_DATA_SOURCES was set but empty/invalid — falling back to defaults"
        )

    sources = [_default_source()]
    assets = _assets_source()
    if assets is not None:
        sources.append(assets)
    space = _space_source()
    if space is not None:
        sources.append(space)
    sources.extend(_sibling_space_sources())
    return tuple(sources)


def get_enabled_sources(
    source_ids: Optional[list[str]] = None,
) -> list[DataSource]:
    sources = [s for s in list_configured_sources() if s.enabled]
    if source_ids:
        wanted = {s.strip() for s in source_ids if s and s.strip()}
        sources = [s for s in sources if s.id in wanted]
    return sources


def select_sources_for_analysis(
    analysis: Any = None,
    source_ids: Optional[list[str]] = None,
) -> list[DataSource]:
    """
    Same source narrowing used by multi-DB retrieve and answer-cache lookup.
    Keep these in sync so /results and /answer hit the same indexes.

    When SEARCH_CATALOG_ENABLED, prefer catalog domain → source mapping so
    queries do not fan out to every database by default.
    """
    sources = get_enabled_sources(source_ids)
    content_types = list(getattr(analysis, "content_types", None) or [])

    original = str(getattr(analysis, "original", "") or "")
    if original:
        from app.search.query_intel import is_bms_domain_query

        if is_bms_domain_query(original):
            bms = [s for s in sources if s.id == "space-bms"]
            if bms:
                return bms

    if content_types == ["team"]:
        bt = [s for s in sources if s.id == "buildtrack"]
        if bt:
            return bt
    space_types = {
        "event",
        "event_agenda",
        "event_information",
        "event_task",
        "event_attendee",
        "event_attachment",
        "event_task_log",
        "event_task_user",
        "event_task_tag",
        "event_task_reference",
        "event_task_attachment",
        "task_reviewprocess",
        "task_reviewprocessstage",
    }
    if content_types and set(content_types).issubset(space_types):
        space = [s for s in sources if s.id == "space"]
        if space:
            return space
    # Any content_type starting with event_ / task_review → Space Action
    if content_types and all(
        t.startswith("event") or t.startswith("task_review") for t in content_types
    ):
        space = [s for s in sources if s.id == "space"]
        if space:
            return space

    project_types = {
        "project",
        "project_location",
        "project_sublocation",
        "project_lms_configuration",
    }
    if content_types and set(content_types).issubset(project_types):
        proj = [s for s in sources if s.id == "space-project"]
        if proj:
            return proj
    if content_types and all(t.startswith("project") for t in content_types):
        proj = [s for s in sources if s.id == "space-project"]
        if proj:
            return proj

    common_types = {
        "person_of_the_month",
        "personofthemonth",
        "personofthemonth_attachment",
        "personofthemonth_nomination",
    }
    if content_types and set(content_types).issubset(common_types):
        common = [s for s in sources if s.id == "space-common"]
        if common:
            return common

    um_types = {
        "user",
        "users",
        "user_contact",
        "user_assignment",
        "user_employment",
        "user_education",
        "user_certification",
        "user_achievement",
        "user_auth",
        "user_attachment",
        "user_professionalinformation",
    }
    if content_types and set(content_types).issubset(um_types):
        um = [s for s in sources if s.id == "space-um"]
        if um:
            return um
    if content_types and all(
        t == "users" or t.startswith("user_") or t == "user" for t in content_types
    ):
        um = [s for s in sources if s.id == "space-um"]
        if um:
            return um

    # Bare "document" is BuildTrack's content type (catalog → buildtrack).
    # Do not steal it for Space DMS — only DMS-specific types route there.
    dms_types = {
        "dms_document",
        "document_file",
        "document_metadata",
        "document_author",
        "document_access",
        "document_downloadhistory",
        "document_externalshare",
        "document_usershare",
        "document_reference",
    }
    if content_types and set(content_types).issubset(dms_types):
        dms = [s for s in sources if s.id == "space-dms"]
        if dms:
            return dms
    if content_types and all(
        t.startswith("document_") or t.startswith("dms") for t in content_types
    ):
        dms = [s for s in sources if s.id == "space-dms"]
        if dms:
            return dms

    attachment_types = {
        "attachment",
        "attachments",
        "attachment_provisional",
        "attachmentreference",
        "attachmentsyncstatus",
    }
    if content_types and set(content_types).issubset(attachment_types):
        att = [s for s in sources if s.id == "space-attachment"]
        if att:
            return att
    if content_types and all(t.startswith("attachment") for t in content_types):
        att = [s for s in sources if s.id == "space-attachment"]
        if att:
            return att

    lms_types = {
        "attendance",
        "labour",
        "labor",
        "contractor",
        "lms",
        "employment",
        "wage",
        "device",
    }
    if content_types and set(content_types).issubset(lms_types):
        lms = [s for s in sources if s.id == "space-lms"]
        if lms:
            return lms
    if content_types and all(
        t in lms_types or t.startswith("labour") or t.startswith("contractor")
        for t in content_types
    ):
        lms = [s for s in sources if s.id == "space-lms"]
        if lms:
            return lms

    hse_incident_types = {
        "safety",
        "hse",
        "incident",
        "environmental_review",
        "occupational_review",
    }
    if content_types and set(content_types).issubset(hse_incident_types):
        picked = [s for s in sources if s.id in ("space-hse", "space-incident")]
        if picked:
            return picked
    if content_types and all(
        t.startswith("incident")
        or t.startswith("environmental")
        or t.startswith("occupational")
        or t in ("safety", "hse")
        for t in content_types
    ):
        if all(t.startswith("incident") for t in content_types):
            inc = [s for s in sources if s.id == "space-incident"]
            if inc:
                return inc
        if all(
            t.startswith("environmental") or t.startswith("occupational") or t == "hse"
            for t in content_types
        ):
            hse = [s for s in sources if s.id == "space-hse"]
            if hse:
                return hse
        picked = [s for s in sources if s.id in ("space-hse", "space-incident")]
        if picked:
            return picked

    admin_types = {
        "company",
        "vendor",
        "material",
        "holiday",
        "region",
        "zone",
        "vertical",
        "admin",
        "picklist",
    }
    if content_types and set(content_types).issubset(admin_types):
        admin = [s for s in sources if s.id == "space-admin"]
        if admin:
            return admin

    bms_types = {"bid", "bids", "tender", "tenders", "bms", "bidding"}
    if content_types and set(content_types).issubset(bms_types):
        bms = [s for s in sources if s.id == "space-bms"]
        if bms:
            return bms
    if content_types and all(
        t.startswith("projectbd") or t in bms_types for t in content_types
    ):
        bms = [s for s in sources if s.id == "space-bms"]
        if bms:
            return bms

    chkwp_types = {
        "submission",
        "submissions",
        "checkpoint",
        "checklist",
        "chkwp",
        "template",
    }
    if content_types and set(content_types).issubset(chkwp_types):
        chkwp = [s for s in sources if s.id == "space-chkwp"]
        if chkwp:
            return chkwp

    cms_types = {"contract", "contracts", "cms", "dispute", "disputes"}
    if content_types and set(content_types).issubset(cms_types):
        cms = [s for s in sources if s.id == "space-cms"]
        if cms:
            return cms
    if content_types and all(
        t.startswith("projectcm") or t in cms_types for t in content_types
    ):
        cms = [s for s in sources if s.id == "space-cms"]
        if cms:
            return cms

    dashboard_types = {"dashboard", "kpi", "pnl"}
    if content_types and set(content_types).issubset(dashboard_types):
        dash = [s for s in sources if s.id == "space-dashboard"]
        if dash:
            return dash
    if content_types and all(t.startswith("dashboard") for t in content_types):
        dash = [s for s in sources if s.id == "space-dashboard"]
        if dash:
            return dash

    notification_types = {"notification", "notifications", "alert", "alerts"}
    if content_types and set(content_types).issubset(notification_types):
        note = [s for s in sources if s.id == "space-notification"]
        if note:
            return note

    analytics_types = {
        "analytics",
        "da_chart",
        "wage_chart",
        "ot_hours",
        "punch_chart",
        "compliance_exceptions",
    }
    if content_types and set(content_types).issubset(analytics_types):
        # Prefer both analytics sources when generic "analytics"
        picked = [
            s
            for s in sources
            if s.id in ("space-analytics", "space-analytics-new")
        ]
        if picked:
            return picked
    if content_types and all(
        t.startswith("da_") or t.startswith("stg_") or t in analytics_types
        for t in content_types
    ):
        picked = [
            s
            for s in sources
            if s.id in ("space-analytics", "space-analytics-new")
        ]
        if picked:
            return picked

    # Catalog-aware routing: only hit sources that own the detected entities.
    if settings.SEARCH_CATALOG_ENABLED and content_types and not source_ids:
        try:
            from app.search.catalog.loader import sources_for_content_types

            wanted = set(sources_for_content_types(content_types))
            if wanted:
                narrowed = [s for s in sources if s.id in wanted]
                if narrowed:
                    return narrowed
        except Exception as exc:
            logger.debug("Catalog source routing skipped: %s", exc)
    return sources


def get_source(source_id: str) -> Optional[DataSource]:
    for source in list_configured_sources():
        if source.id == source_id:
            return source
    return None


@lru_cache(maxsize=16)
def _engine_for(source_id: str) -> Engine:
    source = get_source(source_id)
    if source is None:
        raise KeyError(f"Unknown data source: {source_id}")
    return _create_engine_for_source(source)


@lru_cache(maxsize=16)
def _session_factory(source_id: str) -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=_engine_for(source_id))


def session_for(source_id: str) -> Session:
    """Open a new SQLAlchemy session for the given data source."""
    return _session_factory(source_id)()


def ping_source(source_id: str) -> bool:
    try:
        with _engine_for(source_id).connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Data source %s ping failed: %s", source_id, exc)
        return False


def sources_public_info() -> list[dict[str, Any]]:
    """Safe metadata for API / UI (no connection strings)."""
    configured = list_configured_sources()
    return [
        {
            "id": s.id,
            "label": s.label,
            "search_index": s.search_index or None,
            "blob_index": s.blob_index,
            "enabled": s.enabled,
            "retrieval_mode": s.retrieval_mode,
            "is_primary": s.id == configured[0].id if configured else False,
        }
        for s in configured
    ]


def clear_data_source_caches() -> None:
    """Drop cached engines/factories after config or DB changes."""
    list_configured_sources.cache_clear()
    _engine_for.cache_clear()
    _session_factory.cache_clear()
