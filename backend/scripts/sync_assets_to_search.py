"""
Sync Site Assets SQLite DB → Azure AI Search index (buildtrack-assets-index).

  cd backend
  python -m scripts.sync_assets_to_search
  python -m scripts.sync_assets_to_search --no-embed
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push assets DB into Azure AI Search")
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding vectors (keyword/semantic text only)",
    )
    args = parser.parse_args(argv)

    from app.search.assets_indexer import sync_assets_to_azure_search

    try:
        stats = sync_assets_to_azure_search(embed=not args.no_embed)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(stats, indent=2))
    return 0 if stats.get("uploaded_failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
