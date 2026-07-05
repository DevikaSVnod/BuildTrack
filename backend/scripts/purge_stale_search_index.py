"""
Remove Azure AI Search documents that no longer exist in SQL (vw_global_search_documents).

Usage (from backend/):
  python scripts/purge_stale_search_index.py
  python scripts/purge_stale_search_index.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.search.index_purge import purge_stale_search_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List orphans only")
    args = parser.parse_args()

    stats = purge_stale_search_index(dry_run=args.dry_run)
    print(f"SQL view rows: {stats.get('sql_rows', 0)}")
    print(f"Search index docs: {stats.get('index_docs', 0)}")
    print(f"Stale (orphan) docs: {stats.get('orphans', 0)}")

    if args.dry_run:
        print("Dry run — no deletions.")
    elif stats.get("deleted"):
        print(f"Deleted {stats['deleted']} orphan doc(s).")
        print("SQL indexer triggered.")
    else:
        print("Nothing to purge.")
    print("Done.")


if __name__ == "__main__":
    main()
