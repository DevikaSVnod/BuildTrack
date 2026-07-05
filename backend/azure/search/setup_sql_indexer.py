"""
Provision Azure AI Search SQL Indexer (crawler) for BuildTrack.

Steps:
  1. Enable change tracking + create vw_global_search_documents on Azure SQL
  2. Ensure search index exists (with vector field)
  3. Create SQL data source, embedding skillset, and indexer
  4. Run indexer once

Usage (from backend/):
  python azure/search/setup_sql_indexer.py
  python azure/search/setup_sql_indexer.py --run-only   # skip SQL + provisioning, just run indexer
"""
from __future__ import annotations

import argparse
import sys
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.config import settings
from app.search.indexer import ensure_index_exists, index_has_filter_fields, VECTOR_FIELD, VECTOR_DIM, VECTOR_PROFILE

from app.search.sql_indexer import INDEXER_NAME, DS_NAME, SKILLSET_NAME, SQL_QUERY, SQL_VIEW

INDEX_NAME = settings.AZURE_SEARCH_INDEX


def _require_config() -> None:
    missing = []
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        missing.append("AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY")
    if not settings.AZURE_SQL_CONNECTION_STRING:
        missing.append("AZURE_SQL_CONNECTION_STRING")
    embed_ep = settings.AZURE_OPENAI_EMBEDDING_ENDPOINT or settings.AZURE_OPENAI_ENDPOINT
    embed_key = settings.AZURE_OPENAI_EMBEDDING_KEY or settings.AZURE_OPENAI_KEY
    if not embed_ep or not embed_key:
        missing.append("Azure OpenAI embedding endpoint/key")
    if missing:
        raise SystemExit("Missing configuration:\n  - " + "\n  - ".join(missing))


def _pyodbc_connect(autocommit: bool = True):
    """Build ODBC connection from DATABASE_URL."""
    import pyodbc
    from sqlalchemy.engine import make_url

    url = make_url(settings.DATABASE_URL)
    driver = url.query.get("driver", "ODBC Driver 18 for SQL Server")
    if isinstance(driver, (list, tuple)):
        driver = driver[0]
    driver = driver.replace("+", " ")
    odbc = (
        f"DRIVER={{{driver}}};"
        f"SERVER={url.host},{url.port or 1433};"
        f"DATABASE={url.database};"
        f"UID={url.username};"
        f"PWD={url.password};"
        f"Encrypt=yes;Connection Timeout=120;"
    )
    last_err = None
    for attempt in range(1, 7):
        try:
            return pyodbc.connect(odbc, autocommit=autocommit, timeout=120)
        except Exception as e:
            last_err = e
            if attempt < 6 and "not currently available" in str(e):
                print(f"  DB paused — waking up (attempt {attempt}/6)...")
                time.sleep(20)
            else:
                raise
    raise last_err


def _run_sql(conn, stmt: str) -> None:
    cur = conn.cursor()
    cur.execute(stmt)
    cur.close()


def setup_azure_sql() -> None:
    """Enable change tracking and create the unified search view."""
    print("Setting up Azure SQL (change tracking + search view)...")
    conn = _pyodbc_connect(autocommit=True)

    # Database-level change tracking (requires autocommit)
    try:
        _run_sql(conn, """
            IF NOT EXISTS (SELECT 1 FROM sys.change_tracking_databases WHERE database_id = DB_ID())
            ALTER DATABASE CURRENT SET CHANGE_TRACKING = ON
                (CHANGE_RETENTION = 2 DAYS, AUTO_CLEANUP = ON);
        """)
        print("  Database change tracking enabled.")
    except Exception as e:
        print(f"  Change tracking DB: {e}")

    ops_sql_path = os.path.join(os.path.dirname(__file__), "..", "sql", "002_operational_tables.sql")
    print("  Creating operational tables...")
    with open(ops_sql_path, encoding="utf-8") as f:
        for batch in f.read().split("GO"):
            batch = batch.strip()
            if batch:
                try:
                    _run_sql(conn, batch)
                except Exception as e:
                    print(f"  Operational SQL: {e}")

    for kpi_sql in ("003_kpi_tables.sql", "004_kpi_views.sql"):
        kpi_path = os.path.join(os.path.dirname(__file__), "..", "sql", kpi_sql)
        print(f"  Running {kpi_sql}...")
        with open(kpi_path, encoding="utf-8") as f:
            for batch in f.read().split("GO"):
                batch = batch.strip()
                if batch:
                    try:
                        _run_sql(conn, batch)
                    except Exception as e:
                        print(f"  {kpi_sql}: {e}")

    for table in (
        "users", "projects", "tasks", "documents", "team_members",
        "handover_documents", "engineering_drawings", "safety_incidents",
        "attendance_records", "timeline_phases", "project_financials",
        "dashboard_milestones", "productivity_monthly", "site_activity_weekly",
        "safety_kpi_metrics",
    ):
        try:
            _run_sql(conn, f"ALTER TABLE dbo.{table} ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);")
            print(f"  Change tracking on {table}.")
        except Exception as e:
            print(f"  {table}: {e}")

    view_sql_path = os.path.join(os.path.dirname(__file__), "..", "sql", "001_search_unified_view.sql")
    with open(view_sql_path, encoding="utf-8") as f:
        raw = f.read()
    marker = "CREATE OR ALTER VIEW dbo.vw_global_search_documents"
    idx = raw.upper().find(marker.upper())
    if idx == -1:
        raise SystemExit(f"View definition not found in {view_sql_path}")
    view_block = raw[idx:].split("GO")[0].strip()

    try:
        _run_sql(conn, view_block)
        print("  Search view created/updated.")
    except Exception as e:
        print(f"  View error: {e}")
        raise
    finally:
        conn.close()


def _index_clients():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexerClient

    cred = AzureKeyCredential(settings.AZURE_SEARCH_KEY)
    client = SearchIndexerClient(settings.AZURE_SEARCH_ENDPOINT, cred)
    return client


def provision_indexer() -> None:
    from azure.search.documents.indexes.models import (
        SearchIndexerDataSourceConnection,
        SearchIndexerDataContainer,
        SearchIndexer,
        FieldMapping,
        IndexingSchedule,
        SearchIndexerSkillset,
        AzureOpenAIEmbeddingSkill,
        InputFieldMappingEntry,
        OutputFieldMappingEntry,
    )

    embed_endpoint = (settings.AZURE_OPENAI_EMBEDDING_ENDPOINT or settings.AZURE_OPENAI_ENDPOINT).rstrip("/")
    embed_key = settings.AZURE_OPENAI_EMBEDDING_KEY or settings.AZURE_OPENAI_KEY
    deployment = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT

    print("Ensuring search index...")
    if not ensure_index_exists():
        raise SystemExit(
            "Could not create or update Azure AI Search index. "
            "Check AZURE_SEARCH_* settings and try again."
        )

    client = _index_clients()
    has_filter_fields = index_has_filter_fields()

    print("Creating SQL data source...")
    ds = SearchIndexerDataSourceConnection(
        name=DS_NAME,
        type="azuresql",
        connection_string=settings.AZURE_SQL_CONNECTION_STRING,
        container=SearchIndexerDataContainer(name=SQL_VIEW, query=SQL_QUERY),
        # Full crawl each run (fine for POC dataset size).
        # Incremental change tracking on views requires extra setup on Azure SQL.
    )
    client.create_or_update_data_source_connection(ds)

    print("Creating embedding skillset...")
    embedding_skill = AzureOpenAIEmbeddingSkill(
        description="Embed content for hybrid search",
        context="/document",
        resource_uri=embed_endpoint,
        api_key=embed_key,
        deployment_id=deployment,
        model_name="text-embedding-3-small",
        dimensions=VECTOR_DIM,
        inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
        outputs=[OutputFieldMappingEntry(name="embedding", target_name="vector")],
    )
    skillset = SearchIndexerSkillset(name=SKILLSET_NAME, skills=[embedding_skill])
    client.create_or_update_skillset(skillset)

    print("Creating SQL indexer...")
    field_mappings = [
        FieldMapping(source_field_name="id", target_field_name="id"),
        FieldMapping(source_field_name="title", target_field_name="title"),
        FieldMapping(source_field_name="content", target_field_name="content"),
        FieldMapping(source_field_name="content_type", target_field_name="content_type"),
        FieldMapping(source_field_name="url", target_field_name="url"),
        FieldMapping(source_field_name="metadata", target_field_name="metadata"),
    ]
    if has_filter_fields:
        field_mappings.extend([
            FieldMapping(source_field_name="progress_pct", target_field_name="progress_pct"),
            FieldMapping(source_field_name="record_status", target_field_name="record_status"),
        ])
        print("  Indexer will map progress_pct + record_status (filter fields).")
    else:
        print("  Warning: filter fields not on index — using metadata-only mappings.")

    indexer = SearchIndexer(
        name=INDEXER_NAME,
        description="Crawl Azure SQL → Azure AI Search (every 15 min)",
        data_source_name=DS_NAME,
        target_index_name=INDEX_NAME,
        skillset_name=SKILLSET_NAME,
        schedule=IndexingSchedule(interval="PT15M"),
        field_mappings=field_mappings,
        output_field_mappings=[
            FieldMapping(source_field_name="/document/vector", target_field_name=VECTOR_FIELD),
        ],
    )
    client.create_or_update_indexer(indexer)
    print("Indexer provisioned.")


def run_indexer(wait: bool = True) -> None:
    from app.search.sql_indexer import wait_for_sql_indexer, get_sql_indexer_status

    print(f"Running indexer '{INDEXER_NAME}'...")
    if wait:
        result = wait_for_sql_indexer(timeout_sec=600)
        if result:
            print(
                f"  Status: {result.get('status')} | "
                f"last: {result.get('last_result')} — "
                f"indexed {result.get('last_item_count', 0)} docs"
            )
            for err in result.get("last_errors") or []:
                print(f"    Error: {err}")
    else:
        from app.search.sql_indexer import trigger_sql_indexer_run
        trigger_sql_indexer_run()
    print("Indexer run finished.")


def seed_kpi_on_azure() -> None:
    """Ensure KPI tables have demo rows (safe if already populated)."""
    from app.core.database import SessionLocal
    from app.seed_kpi import seed_kpi_tables

    print("Seeding KPI tables (milestones, productivity, site activity, safety)...")
    db = SessionLocal()
    try:
        n = seed_kpi_tables(db)
        if n:
            print(f"  KPI seed: {n} rows inserted.")
        else:
            print("  KPI tables already populated.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-only", action="store_true", help="Only run indexer (skip SQL + provision)")
    args = parser.parse_args()

    _require_config()

    if not args.run_only:
        setup_azure_sql()
        seed_kpi_on_azure()
        provision_indexer()

    run_indexer()
    print("\nDone. Azure SQL Indexer is active (schedule: every 15 min).")
    print("Search bar will read from Azure AI Search; data syncs from Azure SQL automatically.")

if __name__ == "__main__":
    main()
