"""
Multi-database registry for Global Search.

Each configured source has its own SQL connection and Azure Search index.
When SEARCH_DATA_SOURCES is unset, sources are:
  1) primary DATABASE_URL + AZURE_SEARCH_INDEX
  2) ASSETS_DATABASE_URL (Azure SQL buildtrack_assets on same server)
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
        enabled=True,
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
        enabled=True,
        retrieval_mode="azure" if azure_ready else "sql",
    )


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
    return tuple(sources)


def get_enabled_sources(
    source_ids: Optional[list[str]] = None,
) -> list[DataSource]:
    sources = [s for s in list_configured_sources() if s.enabled]
    if source_ids:
        wanted = {s.strip() for s in source_ids if s and s.strip()}
        sources = [s for s in sources if s.id in wanted]
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
