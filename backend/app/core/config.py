from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env (not cwd-dependent — uvicorn may start from repo root).
_BACKEND_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql://postgres:password@localhost/buildtrack"
    SECRET_KEY: str = "buildtrack-super-secret-jwt-key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    # Skip create_all + seed on every startup (faster restarts after first run)
    SKIP_DB_INIT: bool = False
    # Ping Azure SQL periodically so serverless DB stays awake during dev
    DB_KEEPALIVE_MINUTES: int = 4

    # Multi-database Global Search sources (JSON array). When unset, sources are:
    # 1) DATABASE_URL + AZURE_SEARCH_INDEX
    # 2) ASSETS_DATABASE_URL (or derived buildtrack_assets on same Azure SQL server)
    SEARCH_DATA_SOURCES: Optional[str] = None
    # Second Azure SQL database for Site Assets & Procurement.
    # If unset, derived from DATABASE_URL by swapping DB name → buildtrack_assets.
    ASSETS_DATABASE_URL: Optional[str] = None
    # Optional Space Action SQL Server (e.g. DEV_V1_SPACE_ACTION) for Global Search POC.
    SPACE_DATABASE_URL: Optional[str] = None
    # Optional overrides for sibling Space DBs (else derived by swapping DB name).
    SPACE_PROJECT_DATABASE_URL: Optional[str] = None
    SPACE_COMMON_DATABASE_URL: Optional[str] = None
    SPACE_UM_DATABASE_URL: Optional[str] = None
    SPACE_DMS_DATABASE_URL: Optional[str] = None
    SPACE_ATTACHMENT_DATABASE_URL: Optional[str] = None
    SPACE_LMS_DATABASE_URL: Optional[str] = None
    SPACE_HSE_DATABASE_URL: Optional[str] = None
    SPACE_INCIDENT_DATABASE_URL: Optional[str] = None
    SPACE_ADMIN_DATABASE_URL: Optional[str] = None
    SPACE_BMS_DATABASE_URL: Optional[str] = None
    SPACE_CHKWP_DATABASE_URL: Optional[str] = None
    SPACE_CMS_DATABASE_URL: Optional[str] = None
    SPACE_DASHBOARD_DATABASE_URL: Optional[str] = None
    SPACE_NOTIFICATION_DATABASE_URL: Optional[str] = None
    SPACE_ANALYTICS_DATABASE_URL: Optional[str] = None
    SPACE_ANALYTICS_NEW_DATABASE_URL: Optional[str] = None
    # Cap rows indexed per action.* table (cost control for large tables).
    SPACE_INDEX_MAX_ROWS_PER_TABLE: int = 25000
    # Toggle individual Global Search sources without removing config.
    SEARCH_ENABLE_BUILDTRACK: bool = True
    SEARCH_ENABLE_ASSETS: bool = True
    SEARCH_ENABLE_SPACE: bool = True
    SEARCH_ENABLE_SPACE_PROJECT: bool = True
    SEARCH_ENABLE_SPACE_COMMON: bool = True
    SEARCH_ENABLE_SPACE_UM: bool = True
    SEARCH_ENABLE_SPACE_DMS: bool = True
    SEARCH_ENABLE_SPACE_ATTACHMENT: bool = True
    SEARCH_ENABLE_SPACE_LMS: bool = True
    SEARCH_ENABLE_SPACE_HSE: bool = True
    SEARCH_ENABLE_SPACE_INCIDENT: bool = True
    SEARCH_ENABLE_SPACE_ADMIN: bool = True
    SEARCH_ENABLE_SPACE_BMS: bool = True
    SEARCH_ENABLE_SPACE_CHKWP: bool = True
    SEARCH_ENABLE_SPACE_CMS: bool = True
    SEARCH_ENABLE_SPACE_DASHBOARD: bool = True
    SEARCH_ENABLE_SPACE_NOTIFICATION: bool = True
    SEARCH_ENABLE_SPACE_ANALYTICS: bool = True
    SEARCH_ENABLE_SPACE_ANALYTICS_NEW: bool = True

    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_KEY: Optional[str] = None
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o-mini"
    # Optional: vision-capable deployment for drawing sheet Q&A (e.g., gpt-4o)
    AZURE_OPENAI_VISION_DEPLOYMENT: Optional[str] = None

    # Embedding model — can live in a separate Azure OpenAI resource.
    # If AZURE_OPENAI_EMBEDDING_ENDPOINT / AZURE_OPENAI_EMBEDDING_KEY are not set,
    # they fall back to the chat endpoint/key above.
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    AZURE_OPENAI_EMBEDDING_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_EMBEDDING_KEY: Optional[str] = None

    AZURE_SEARCH_ENDPOINT: Optional[str] = None
    AZURE_SEARCH_KEY: Optional[str] = None
    AZURE_SEARCH_INDEX: str = "buildtrack-index"
    # Second DB (Site Assets) — separate Azure AI Search index for multi-DB hybrid search
    AZURE_SEARCH_ASSETS_INDEX: str = "buildtrack-assets-index"
    # Space Action DB — separate Azure AI Search index for Events / Agenda POC
    AZURE_SEARCH_SPACE_INDEX: str = "space-action-index"
    # Schema catalog index (table/column descriptions — not row data)
    AZURE_SEARCH_SCHEMA_INDEX: str = "space-schema-index"
    # Schema-first SQL retrieval (Phase 1)
    SCHEMA_SQL_ENABLED: bool = True
    SCHEMA_SQL_MAX_ROWS: int = 50
    SCHEMA_SQL_TIMEOUT_SECONDS: int = 15
    SCHEMA_SQL_TOP_TABLES: int = 6
    # RAG / blob content index (Portal wizard). Auto-discovered if unset.
    AZURE_SEARCH_BLOB_INDEX: Optional[str] = None

    # Azure SQL (target architecture — SQL indexer data source)
    AZURE_SQL_CONNECTION_STRING: Optional[str] = None

    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_STORAGE_CONTAINER: str = "buildtrack-documents"

    # Production search architecture flags (DB = SoT, AI Search = discovery)
    # When True, page/list reads and search hits hydrate authoritative rows from SQL.
    SEARCH_HYDRATE_FROM_SQL: bool = True
    # When True, catalog YAML drives document building, routing, and hydration SELECTs.
    SEARCH_CATALOG_ENABLED: bool = True
    # When True, push sync uses watermarks + content-hash gated embeddings.
    SEARCH_INCREMENTAL_SYNC: bool = True
    # When True, apply ACL OData filters from the current user on search.
    SEARCH_SECURITY_TRIMMING: bool = True
    # When True, file-content questions prefer blob/RAG chunk index over fat body text.
    SEARCH_CHUNK_INDEX_FOR_DOCS: bool = True

    # SPACE header integration (Phase 1): fan-out to module APIs with the
    # caller's SPACE JWT. Used when the Bearer token is not a BuildTrack JWT.
    # Do not query SPACE SQL from this path.
    SPACE_ACTION_API_URL: Optional[str] = "http://192.168.138.21:8000/action"
    SPACE_CMS_API_URL: Optional[str] = "http://192.168.138.21:8000/cms"
    SPACE_DMS_API_URL: Optional[str] = "http://192.168.138.21:8000/dms"
    SPACE_INCIDENT_API_URL: Optional[str] = "http://192.168.138.21:8000/incident"
    SPACE_CHKWP_API_URL: Optional[str] = "http://192.168.138.21:8000/chkwp"
    SPACE_MODULE_SEARCH_TIMEOUT_SECONDS: float = 5.0
    # Action API: "" = RaisedByMe. Do not send a client-invented "all visible".
    SPACE_MEETING_ASSIGNMENT_OPTION: str = ""
    # Phase 2: Azure returns candidate ids only. Module APIs remain source of truth.
    SPACE_AZURE_DISCOVERY: bool = True
    SPACE_AZURE_INDEX: Optional[str] = None
    SPACE_AZURE_API_VERSION: str = "2024-07-01"
    # Same issuer/audience as SPACE.Gateway Jwt (identity comes from this token).
    SPACE_JWT_KEY: Optional[str] = "Yh2k7QSu4l8CZg5p6X3Pna9L0Miy4D3Bvt0JVr87UcOj69Kqw5R2Nmf4FWs03Hdx"
    SPACE_JWT_ISSUER: str = "JWTAuthenticationServer"
    SPACE_JWT_AUDIENCE: str = "JWTServicePostmanClient"
    # Extra CORS origins for the SPACE webpack shell (comma-separated).
    SPACE_CORS_ORIGINS: str = "http://localhost:4200,http://127.0.0.1:4200"


settings = Settings()
