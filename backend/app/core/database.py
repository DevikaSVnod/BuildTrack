import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

logger = logging.getLogger(__name__)


def _engine_kwargs() -> dict:
    url = settings.DATABASE_URL
    common = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 1800,
        "pool_timeout": 15,
    }
    if url.startswith("mssql"):
        # Azure SQL: balance cold-start tolerance vs not blocking every request for 2 min
        return {
            **common,
            "connect_args": {"timeout": 45},
        }
    return common


engine = create_engine(settings.DATABASE_URL, **_engine_kwargs())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping_database() -> bool:
    """Lightweight query to keep Azure SQL awake and verify connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database ping failed: %s", exc)
        return False


_columns_checked = False


def ensure_drawing_file_columns() -> None:
    """Add file_url/file_type/file_size to engineering_drawings if missing (Azure SQL)."""
    global _columns_checked
    if _columns_checked:
        return
    if not settings.DATABASE_URL.startswith("mssql"):
        _columns_checked = True
        return
    alters = [
        "IF COL_LENGTH('dbo.engineering_drawings', 'file_url') IS NULL "
        "ALTER TABLE dbo.engineering_drawings ADD file_url NVARCHAR(1000) NULL",
        "IF COL_LENGTH('dbo.engineering_drawings', 'file_type') IS NULL "
        "ALTER TABLE dbo.engineering_drawings ADD file_type NVARCHAR(20) NULL",
        "IF COL_LENGTH('dbo.engineering_drawings', 'file_size') IS NULL "
        "ALTER TABLE dbo.engineering_drawings ADD file_size BIGINT NULL",
        "IF COL_LENGTH('dbo.engineering_drawings', 'sheet_notes') IS NULL "
        "ALTER TABLE dbo.engineering_drawings ADD sheet_notes NVARCHAR(MAX) NULL",
        "IF COL_LENGTH('dbo.engineering_drawings', 'preview_url') IS NULL "
        "ALTER TABLE dbo.engineering_drawings ADD preview_url NVARCHAR(1000) NULL",
    ]
    try:
        with engine.begin() as conn:
            for stmt in alters:
                conn.execute(text(stmt))
    except Exception as exc:
        logger.warning("Could not ensure drawing file columns: %s", exc)
    finally:
        _columns_checked = True
