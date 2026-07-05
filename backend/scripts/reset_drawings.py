"""
Remove all engineering drawing rows from SQL (clears demo/seed drawings).

Drawings are added only via the website upload flow (Drawings page).
After clearing, upload files through the UI — they go to blob + auto-index.

Usage (from backend/):
  python scripts/reset_drawings.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.operational import EngineeringDrawing
from app.search.sql_indexer import trigger_sql_indexer_run
from app.search.blob_indexer import trigger_blob_indexer_run
from app.search.index_purge import purge_stale_search_index


def main() -> None:
    db = SessionLocal()
    try:
        deleted = db.query(EngineeringDrawing).delete()
        db.commit()
        print(f"Deleted {deleted} drawing row(s) from SQL.")
        print("Upload new drawings via the Drawings page in the website.")

        try:
            stats = purge_stale_search_index(reindex=False)
            if stats.get("deleted"):
                print(f"Purged {stats['deleted']} stale search index doc(s).")
        except Exception as exc:
            print(f"Stale index purge failed: {exc}")

        try:
            trigger_sql_indexer_run()
            print("SQL indexer triggered.")
        except Exception as exc:
            print(f"SQL indexer trigger failed: {exc}")
        try:
            for name in trigger_blob_indexer_run():
                print(f"Triggered blob indexer: {name}")
        except Exception as exc:
            print(f"Blob indexer trigger failed: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
