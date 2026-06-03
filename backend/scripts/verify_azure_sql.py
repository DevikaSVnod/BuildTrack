"""Quick connectivity check for Azure SQL. Run from backend/: python scripts/verify_azure_sql.py"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.database import engine
from sqlalchemy import text


def main() -> None:
    url = settings.DATABASE_URL
    if not url.startswith("mssql"):
        print("DATABASE_URL is not mssql — still pointing at PostgreSQL/local DB.")
        print(f"  Current prefix: {url.split('://')[0]}")
        sys.exit(1)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT @@VERSION")).scalar()
        db_name = conn.execute(text("SELECT DB_NAME()")).scalar()
    print("Azure SQL connection OK")
    print(f"  Database: {db_name}")
    print(f"  Server:   {version.split(chr(10))[0][:120]}...")


if __name__ == "__main__":
    main()
