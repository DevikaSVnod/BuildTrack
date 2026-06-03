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

    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_KEY: Optional[str] = None
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o-mini"

    # Embedding model — can live in a separate Azure OpenAI resource.
    # If AZURE_OPENAI_EMBEDDING_ENDPOINT / AZURE_OPENAI_EMBEDDING_KEY are not set,
    # they fall back to the chat endpoint/key above.
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    AZURE_OPENAI_EMBEDDING_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_EMBEDDING_KEY: Optional[str] = None

    AZURE_SEARCH_ENDPOINT: Optional[str] = None
    AZURE_SEARCH_KEY: Optional[str] = None
    AZURE_SEARCH_INDEX: str = "buildtrack-index"

    # Azure SQL (target architecture — SQL indexer data source)
    AZURE_SQL_CONNECTION_STRING: Optional[str] = None

    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_STORAGE_CONTAINER: str = "buildtrack-documents"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
