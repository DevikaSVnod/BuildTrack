"""
DEPRECATED — use azure/search/setup_sql_indexer.py instead.

That script is the single provisioning path: SQL view + SQL Indexer + embedding skillset.
Manual Python indexing is not used in this project.
"""

Environment (.env):
  AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX
  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_EMBEDDING_DEPLOYMENT
  AZURE_SQL_CONNECTION_STRING  (ADO.NET or ODBC for indexer data source)
  AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.config import settings  # noqa: E402


INDEX_NAME = settings.AZURE_SEARCH_INDEX
VECTOR_FIELD = "content_vector"
VECTOR_DIM = 1536


def _require(*names: str) -> None:
    missing = [n for n in names if not getattr(settings, n, None)]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")


def build_index_definition():
    """Search index schema — shared by SQL indexer and Blob indexer."""
    return {
        "name": INDEX_NAME,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "title", "type": "Edm.String", "searchable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "content_type", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "url", "type": "Edm.String", "retrievable": True},
            {"name": "metadata", "type": "Edm.String", "retrievable": True},
            {
                "name": VECTOR_FIELD,
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "dimensions": VECTOR_DIM,
                "vectorSearchProfile": "buildtrack-hnsw",
            },
        ],
        "semantic": {
            "configurations": [
                {
                    "name": "default",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "title"},
                        "contentFields": [{"fieldName": "content"}],
                    },
                }
            ]
        },
        "vectorSearch": {
            "algorithms": [{"name": "buildtrack-hnsw-algo", "kind": "hnsw"}],
            "profiles": [
                {
                    "name": "buildtrack-hnsw",
                    "algorithm": "buildtrack-hnsw-algo",
                }
            ],
        },
    }


def print_setup_checklist() -> None:
    print(
        """
=== Azure architecture checklist ===

[SQL path]
  • Migrate PostgreSQL → Azure SQL Database
  • Run: azure/sql/001_search_unified_view.sql
  • Enable change tracking on source tables
  • Create indexer data source → vw_global_search_documents

[Blob path]
  • Upload PDFs/XLSX/DWG to Azure Blob container
  • Blob indexer extracts text (Document Intelligence skill optional)
  • Same index: id prefix 'blob-{filename}' content_type 'document'

[Integrated vectorization]
  • Skillset: AzureOpenAIEmbeddingSkill on 'content' field
  • Index projection maps output → content_vector
  • Query-time: vectorizer on same embedding deployment

[FastAPI keeps]
  • Auth, CRUD, query intelligence, workforce DB filter, AI answer UI
  • Remove manual POST /search/index once indexers run on schedule

[Indexers schedule]
  • SQL indexer: every 5–15 minutes (incremental)
  • Blob indexer: every 15–60 minutes
"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Azure Search indexer provisioning helper")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    args = parser.parse_args()

    print_setup_checklist()

    if args.dry_run:
        print("Dry run — index schema preview:")
        import json
        print(json.dumps(build_index_definition(), indent=2))
        print("\nNext: configure data sources + indexers in Azure Portal or extend this script.")
        return

    _require(
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_KEY",
    )
    print(
        "Use Azure Portal → AI Search → Import data → Azure SQL / Blob\n"
        "Or extend this script with azure-search-documents IndexerClient.\n"
        f"Target index: {INDEX_NAME}"
    )


if __name__ == "__main__":
    main()
