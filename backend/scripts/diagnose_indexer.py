"""Diagnose vw_global_search_documents for Azure SQL Indexer issues."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from azure.search.setup_sql_indexer import _pyodbc_connect

conn = _pyodbc_connect()
cur = conn.cursor()

cur.execute(
    "SELECT id, COUNT(*) c FROM dbo.vw_global_search_documents "
    "GROUP BY id HAVING COUNT(*) > 1"
)
print("duplicate ids:", cur.fetchall())

cur.execute(
    "SELECT id FROM dbo.vw_global_search_documents "
    "WHERE id IS NULL OR title IS NULL OR content IS NULL OR content_type IS NULL"
)
print("null required fields:", cur.fetchall())

cur.execute("SELECT COUNT(*) FROM dbo.vw_search_kpi_rows")
print("kpi rows:", cur.fetchone()[0])

cur.execute("SELECT id, LEN(content) AS lc, LEN(metadata) AS lm FROM dbo.vw_search_kpi_rows")
for r in cur.fetchall():
    print("KPI", r)

cur.execute(
    "SELECT id, LEN(content) AS lc, LEN(CAST(metadata AS NVARCHAR(MAX))) AS lm "
    "FROM dbo.vw_global_search_documents ORDER BY lc DESC"
)
print("top 5 longest content:")
for r in cur.fetchall()[:5]:
    print(r)

# Check for old team-* rows still in unified view
cur.execute(
    "SELECT id, content_type FROM dbo.vw_global_search_documents "
    "WHERE id LIKE 'team-%'"
)
print("legacy team-* rows:", len(cur.fetchall()))

cur.execute(
    "SELECT id FROM dbo.vw_global_search_documents WHERE id LIKE 'team-%'"
)
for r in cur.fetchall()[:5]:
    print(" ", r[0])

conn.close()
