"""
Sync Space Action SQL (Events / Event_Agenda / Event_Information)
→ Azure AI Search index (space-action-index).

  cd backend
  python -m scripts.sync_space_to_search
  python -m scripts.sync_space_to_search --no-embed
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Push Space Action DB into Azure AI Search"
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding vectors (keyword/semantic text only)",
    )
    args = parser.parse_args(argv)

    from app.core.data_sources import clear_data_source_caches
    from app.search.space_indexer import sync_space_to_azure_search

    clear_data_source_caches()
    try:
        stats = sync_space_to_azure_search(embed=not args.no_embed)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(stats, indent=2))
    return 0 if stats.get("uploaded_failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
