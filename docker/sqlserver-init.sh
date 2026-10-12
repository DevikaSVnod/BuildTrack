#!/bin/bash
# Wait for SQL Server, then create the primary app database if missing.
# (buildtrack_assets is created later by the backend's ensure_assets_database().)
set -e

SA_PASSWORD="${SQL_SA_PASSWORD:-YourStr0ng_Passw0rd!}"
HOST="${SQL_HOST:-sqlserver}"

echo "Waiting for SQL Server at ${HOST}â€¦"
for i in $(seq 1 60); do
  if /opt/mssql-tools18/bin/sqlcmd -S "$HOST" -U sa -P "$SA_PASSWORD" -C -Q "SELECT 1" -b -o /dev/null 2>/dev/null; then
    echo "SQL Server is up."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "ERROR: SQL Server did not become ready in time."
    exit 1
  fi
  sleep 3
done

echo "Ensuring database [buildtrack] existsâ€¦"
/opt/mssql-tools18/bin/sqlcmd -S "$HOST" -U sa -P "$SA_PASSWORD" -C -Q "
IF DB_ID(N'buildtrack') IS NULL
BEGIN
  CREATE DATABASE [buildtrack];
  PRINT 'Created database buildtrack';
END
ELSE
  PRINT 'Database buildtrack already exists';
"

echo "SQL init done."
