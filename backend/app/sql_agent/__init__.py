"""Safe SQL generation, validation, and read-only execution for schema-first search."""

from app.sql_agent.pipeline import run_schema_sql_retrieval

__all__ = ["run_schema_sql_retrieval"]
