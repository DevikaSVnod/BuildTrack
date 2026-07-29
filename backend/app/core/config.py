from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
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
    # RAG / blob content index (Portal wizard). Auto-discovered if unset.
    AZURE_SEARCH_BLOB_INDEX: Optional[str] = None

    # Azure SQL (target architecture — SQL indexer data source)
    AZURE_SQL_CONNECTION_STRING: Optional[str] = None

    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_STORAGE_CONTAINER: str = "buildtrack-documents"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
