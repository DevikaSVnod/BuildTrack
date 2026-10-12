"""Generate a single SELECT using only retrieved schema context."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.core.config import settings
from app.schema_catalog.models import TableInfo
from app.schema_catalog.search import format_schema_for_prompt

logger = logging.getLogger(__name__)


def generate_select_sql(
    query: str,
    tables: list[TableInfo],
    *,
    database_name: str = "DEV_V1_SPACE_ACTION",
    max_rows: Optional[int] = None,
) -> dict[str, Any]:
    """
    Returns {sql, tables_used, rationale} or {error}.
    """
    if not tables:
        return {"error": "No relevant schema tables for SQL generation"}
    if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_KEY:
        return {"error": "Azure OpenAI is not configured"}

    limit = max_rows or settings.SCHEMA_SQL_MAX_ROWS or 50
    schema_block = format_schema_for_prompt(tables, database_name=database_name)
    schemas = sorted({(t.schema_name or "dbo") for t in tables})
    schema_hint = schemas[0] if len(schemas) == 1 else "the provided schema(s)"
    table_list = ", ".join(
        f"{t.schema_name or 'dbo'}.[{t.name}]" for t in tables
    )

    system = (
        "You write safe Microsoft SQL Server SELECT queries only. "
        "Return JSON with keys: sql, tables_used (array of table names), rationale. "
        f"Rules: SELECT/WITH only; SQL schema name is '{schema_hint}' "
        f"(never use the database name '{database_name}' as a schema); "
        f"qualify tables exactly like {schema_hint}.TableName; "
        f"include TOP ({limit}); never modify data; only use provided tables/columns; "
        "always include each table's primary key column(s) and any ProjectId/UserId/"
        "DocumentId columns in the SELECT list (needed for cross-database linking)."
    )
    user = (
        f"User question: {query}\n\n"
        f"Database (do not use as schema): {database_name}\n"
        f"Allowed tables: {table_list}\n\n"
        f"Schema:\n{schema_block}\n\n"
        "Write one T-SQL SELECT that answers the question. "
        "Include primary keys and ProjectId/UserId/DocumentId when those columns exist."
    )

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=600,
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = (resp.choices[0].message.content or "").strip()
        payload = json.loads(text)
        sql = str(payload.get("sql") or "").strip()
        # Strip markdown fences if model ignored JSON shape partially
        sql = re.sub(r"^```sql\s*|\s*```$", "", sql, flags=re.IGNORECASE).strip()
        tables_used = payload.get("tables_used") or [t.name for t in tables]
        if isinstance(tables_used, str):
            tables_used = [tables_used]
        return {
            "sql": sql,
            "tables_used": list(tables_used),
            "rationale": str(payload.get("rationale") or ""),
        }
    except Exception as exc:
        logger.warning("SQL generation failed: %s", exc)
        return {"error": f"SQL generation failed: {exc}"}
