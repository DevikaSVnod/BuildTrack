"""Registry of Space SQL databases for schema-first Global Search."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from sqlalchemy.engine import URL, make_url

from app.core.config import settings

_DEFAULT_EXCLUDED = frozenset(
    {
        "OfflineSyncLog",
        "Synonyms_Configuration",
        "__EFMigrationsHistory",
        "sysdiagrams",
        "IdempotencyRequests",
        "NotificationExecutions",
    }
)

# Analytics DBs include Django/auth scaffolding + test tables — skip those.
_ANALYTICS_EXCLUDED = _DEFAULT_EXCLUDED | frozenset(
    {
        "auth_group",
        "auth_group_permissions",
        "auth_permission",
        "auth_user",
        "auth_user_groups",
        "auth_user_user_permissions",
        "django_admin_log",
        "django_content_type",
        "django_migrations",
        "django_session",
        "django_celery_results_chordcounter",
        "django_celery_results_groupresult",
        "django_celery_results_taskresult",
        "django_redirect",
        "django_site",
        "my_cache_table",
        "Student",
        "tblAddress",
        "tblCustomer",
        "testapis_todo",
        "Employee",
        "Final",
        "my_Trace",
        "myTrace",
    }
)


@dataclass(frozen=True)
class SpaceDbConfig:
    source_id: str
    label: str
    database_name: str
    schema_name: str
    has_row_index: bool = False
    excluded_tables: frozenset[str] = _DEFAULT_EXCLUDED


# Ordered onboarding list — enable via SEARCH_ENABLE_SPACE_* flags.
_KNOWN: tuple[SpaceDbConfig, ...] = (
    SpaceDbConfig(
        source_id="space",
        label="Space Action",
        database_name="DEV_V1_SPACE_ACTION",
        schema_name="action",
        has_row_index=True,
    ),
    SpaceDbConfig(
        source_id="space-project",
        label="Space Project",
        database_name="DEV_V1_SPACE_PROJECT",
        schema_name="project",
    ),
    SpaceDbConfig(
        source_id="space-common",
        label="Space Common",
        database_name="DEV_V1_SPACE_COMMON",
        schema_name="common",
    ),
    SpaceDbConfig(
        source_id="space-um",
        label="Space User Management",
        database_name="DEV_V1_SPACE_UM",
        schema_name="um",
    ),
    SpaceDbConfig(
        source_id="space-dms",
        label="Space DMS",
        database_name="DEV_V1_SPACE_DMS",
        schema_name="dms",
    ),
    SpaceDbConfig(
        source_id="space-attachment",
        label="Space Attachment",
        database_name="DEV_V1_SPACE_ATTACHMENT",
        schema_name="storage",
    ),
    SpaceDbConfig(
        source_id="space-lms",
        label="Space LMS",
        database_name="DEV_V1_SPACE_LMS",
        schema_name="lms",
    ),
    SpaceDbConfig(
        source_id="space-hse",
        label="Space HSE",
        database_name="DEV_V1_SPACE_HSE",
        schema_name="hse",
    ),
    SpaceDbConfig(
        source_id="space-incident",
        label="Space Incident",
        database_name="DEV_V1_SPACE_INCIDENT",
        schema_name="incident",
    ),
    SpaceDbConfig(
        source_id="space-admin",
        label="Space Admin",
        database_name="DEV_V1_SPACE_ADMIN",
        schema_name="admin",
    ),
    SpaceDbConfig(
        source_id="space-bms",
        label="Space BMS",
        database_name="DEV_V1_SPACE_BMS",
        schema_name="bms",
    ),
    SpaceDbConfig(
        source_id="space-chkwp",
        label="Space Checkpoints",
        database_name="DEV_V1_SPACE_CHKWP",
        schema_name="chkwp",
    ),
    SpaceDbConfig(
        source_id="space-cms",
        label="Space CMS",
        database_name="DEV_V1_SPACE_CMS",
        schema_name="cms",
    ),
    SpaceDbConfig(
        source_id="space-dashboard",
        label="Space Dashboard",
        database_name="DEV_V1_SPACE_DASHBOARD",
        schema_name="dbo",
    ),
    SpaceDbConfig(
        source_id="space-notification",
        label="Space Notification",
        database_name="DEV_V1_SPACE_NOTIFICATION",
        schema_name="notification",
    ),
    # Analytics last — schema-only; dbo charts (skip mirrored lms.* — use space-lms).
    SpaceDbConfig(
        source_id="space-analytics",
        label="Space Analytics",
        database_name="DEV_V1_SPACE_ANALYTICS",
        schema_name="dbo",
        excluded_tables=_ANALYTICS_EXCLUDED,
    ),
    SpaceDbConfig(
        source_id="space-analytics-new",
        label="Space Analytics New",
        database_name="DEV_V1_SPACE_ANALYTICS_NEW",
        schema_name="dbo",
        excluded_tables=_ANALYTICS_EXCLUDED,
    ),
)

_ENABLE_ATTR: dict[str, str] = {
    "space": "SEARCH_ENABLE_SPACE",
    "space-project": "SEARCH_ENABLE_SPACE_PROJECT",
    "space-common": "SEARCH_ENABLE_SPACE_COMMON",
    "space-um": "SEARCH_ENABLE_SPACE_UM",
    "space-dms": "SEARCH_ENABLE_SPACE_DMS",
    "space-attachment": "SEARCH_ENABLE_SPACE_ATTACHMENT",
    "space-lms": "SEARCH_ENABLE_SPACE_LMS",
    "space-hse": "SEARCH_ENABLE_SPACE_HSE",
    "space-incident": "SEARCH_ENABLE_SPACE_INCIDENT",
    "space-admin": "SEARCH_ENABLE_SPACE_ADMIN",
    "space-bms": "SEARCH_ENABLE_SPACE_BMS",
    "space-chkwp": "SEARCH_ENABLE_SPACE_CHKWP",
    "space-cms": "SEARCH_ENABLE_SPACE_CMS",
    "space-dashboard": "SEARCH_ENABLE_SPACE_DASHBOARD",
    "space-notification": "SEARCH_ENABLE_SPACE_NOTIFICATION",
    "space-analytics": "SEARCH_ENABLE_SPACE_ANALYTICS",
    "space-analytics-new": "SEARCH_ENABLE_SPACE_ANALYTICS_NEW",
}

_URL_OVERRIDE_ATTR: dict[str, str] = {
    "space-project": "SPACE_PROJECT_DATABASE_URL",
    "space-common": "SPACE_COMMON_DATABASE_URL",
    "space-um": "SPACE_UM_DATABASE_URL",
    "space-dms": "SPACE_DMS_DATABASE_URL",
    "space-attachment": "SPACE_ATTACHMENT_DATABASE_URL",
    "space-lms": "SPACE_LMS_DATABASE_URL",
    "space-hse": "SPACE_HSE_DATABASE_URL",
    "space-incident": "SPACE_INCIDENT_DATABASE_URL",
    "space-admin": "SPACE_ADMIN_DATABASE_URL",
    "space-bms": "SPACE_BMS_DATABASE_URL",
    "space-chkwp": "SPACE_CHKWP_DATABASE_URL",
    "space-cms": "SPACE_CMS_DATABASE_URL",
    "space-dashboard": "SPACE_DASHBOARD_DATABASE_URL",
    "space-notification": "SPACE_NOTIFICATION_DATABASE_URL",
    "space-analytics": "SPACE_ANALYTICS_DATABASE_URL",
    "space-analytics-new": "SPACE_ANALYTICS_NEW_DATABASE_URL",
}


def is_space_source_id(source_id: Optional[str]) -> bool:
    sid = (source_id or "").strip()
    return sid == "space" or sid.startswith("space-")


def get_space_db_config(source_id: str) -> Optional[SpaceDbConfig]:
    for cfg in _KNOWN:
        if cfg.source_id == source_id:
            return cfg
    return None


def is_space_db_enabled(cfg: SpaceDbConfig) -> bool:
    attr = _ENABLE_ATTR.get(cfg.source_id)
    if not attr:
        return False
    return bool(getattr(settings, attr, False))


def list_known_space_db_configs() -> tuple[SpaceDbConfig, ...]:
    return _KNOWN


@lru_cache(maxsize=1)
def list_space_db_configs(*, enabled_only: bool = True) -> tuple[SpaceDbConfig, ...]:
    if not (settings.SPACE_DATABASE_URL or "").strip():
        return ()
    out: list[SpaceDbConfig] = []
    for cfg in _KNOWN:
        if enabled_only and not is_space_db_enabled(cfg):
            continue
        out.append(cfg)
    return tuple(out)


def resolve_space_database_url(cfg: SpaceDbConfig) -> URL:
    """
    Build a SQLAlchemy URL for a Space DB.
    Prefer explicit override env when set; else swap DB name on SPACE_DATABASE_URL.
    """
    override_attr = _URL_OVERRIDE_ATTR.get(cfg.source_id)
    if override_attr:
        override = (getattr(settings, override_attr, None) or "").strip()
        if override:
            return make_url(override)

    base = (settings.SPACE_DATABASE_URL or "").strip()
    if not base:
        raise RuntimeError("SPACE_DATABASE_URL is not set")
    url = make_url(base)
    if cfg.source_id == "space" and (url.database or "") == cfg.database_name:
        return url
    return url.set(database=cfg.database_name)


def clear_space_db_cache() -> None:
    list_space_db_configs.cache_clear()
