import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from azure.search.setup_sql_indexer import _pyodbc_connect

conn = _pyodbc_connect()
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM dbo.vw_global_search_documents")
print("View row count:", cur.fetchone()[0])
cur.execute("SELECT TOP 3 id, title, content_type FROM dbo.vw_global_search_documents")
for r in cur.fetchall():
    print(r)
conn.close()
