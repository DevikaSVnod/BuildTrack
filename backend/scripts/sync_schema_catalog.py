"""
Refresh Space schema catalog(s) and sync table docs to Azure AI Search.

  cd backend
  python -m scripts.sync_schema_catalog
  python -m scripts.sync_schema_catalog --no-embed
  python -m scripts.sync_schema_catalog --source space-project
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync Space schema catalog into Azure AI Search"
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding vectors",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Optional Space source_id (e.g. space, space-project). Default: all enabled.",
    )
    args = parser.parse_args(argv)

    from app.schema_catalog.indexer import sync_schema_catalog_to_azure_search

    try:
        stats = sync_schema_catalog_to_azure_search(
            embed=not args.no_embed,
            source_id=args.source,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(stats, indent=2, default=str))
    return 0 if stats.get("uploaded_failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
