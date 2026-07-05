"""
Re-extract searchable text from drawing files and upload RAG sidecars.

Text is read from the actual PNG/DWG file (vision OCR or DWG strings) — not from code.

Usage (from backend/):
  python scripts/sync_drawing_crawl_sidecars.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.database import SessionLocal, ensure_drawing_file_columns
from app.models.operational import EngineeringDrawing
from app.search.blob_indexer import trigger_blob_indexer_run
from app.search.sql_indexer import trigger_sql_indexer_run
from app.storage.drawing_index import index_drawing_search_text

def main() -> None:
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise SystemExit("Set AZURE_STORAGE_CONNECTION_STRING in backend/.env")

    ensure_drawing_file_columns()
    db = SessionLocal()
    indexed = 0
    try:
        drawings = (
            db.query(EngineeringDrawing)
            .options(joinedload(EngineeringDrawing.project))
            .order_by(EngineeringDrawing.drawing_no)
            .all()
        )
        for drawing in drawings:
            try:
                notes = index_drawing_search_text(drawing, db=db)
                preview = (notes or "")[:80].replace("\n", " ")
                print(f"  indexed {drawing.drawing_no}: {preview}...")
                indexed += 1
            except Exception as exc:
                print(f"  FAILED {drawing.drawing_no}: {exc}")

        if indexed:
            trigger_sql_indexer_run()
            print("SQL indexer triggered.")
            for name in trigger_blob_indexer_run():
                print(f"Triggered blob indexer: {name}")
        print(f"Done: {indexed} drawing(s) indexed from file content.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
