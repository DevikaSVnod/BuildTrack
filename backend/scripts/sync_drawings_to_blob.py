"""
Re-index drawing search text from blob files already in SQL.

Drawings must be uploaded via the website first (blob + SQL row).
This script re-runs text extraction and sidecar upload for every row.

Usage (from backend/):
  python scripts/sync_drawings_to_blob.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.database import SessionLocal, ensure_drawing_file_columns
from app.models.operational import EngineeringDrawing
from app.search.sql_indexer import trigger_sql_indexer_run
from app.search.blob_indexer import trigger_blob_indexer_run
from app.storage.document_blob import is_blob_url
from app.storage.drawing_index import index_drawing_search_text


def main() -> None:
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise SystemExit("Set AZURE_STORAGE_CONNECTION_STRING in backend/.env")

    ensure_drawing_file_columns()
    db = SessionLocal()
    indexed = skipped = failed = 0
    try:
        drawings = (
            db.query(EngineeringDrawing)
            .options(joinedload(EngineeringDrawing.project))
            .order_by(EngineeringDrawing.drawing_no)
            .all()
        )
        print(f"Found {len(drawings)} drawing row(s) in SQL.")

        for drawing in drawings:
            if not is_blob_url(drawing.file_url):
                print(f"  skip {drawing.drawing_no}: no blob file (upload via website first)")
                skipped += 1
                continue
            try:
                index_drawing_search_text(drawing, db=db)
                print(f"  indexed {drawing.drawing_no}")
                indexed += 1
            except Exception as exc:
                print(f"  FAILED {drawing.drawing_no}: {exc}")
                failed += 1

        if indexed:
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

        print(f"\nDone: indexed={indexed}, skipped={skipped}, failed={failed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
