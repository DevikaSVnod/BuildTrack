"""
Rebuild extracted body_text for existing documents (no re-upload needed).

Usage (from backend/):
  py -3.10 scripts/rebuild_document_body_text.py
  py -3.10 scripts/rebuild_document_body_text.py --doc-id 15
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal, ensure_document_columns
from app.models.document import Document
from app.storage.document_index import index_document_search_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", type=int, default=None)
    args = parser.parse_args()

    ensure_document_columns()
    db = SessionLocal()
    try:
        q = db.query(Document)
        if args.doc_id is not None:
            q = q.filter(Document.id == args.doc_id)
        rows = q.order_by(Document.id.desc()).all()
        print(f"Rebuilding body_text for {len(rows)} document(s)...")
        ok = 0
        for row in rows:
            try:
                text = index_document_search_text(row, db=db)
                chars = len(text or "")
                if chars:
                    print(f"  ok document-{row.id}: {row.name[:60]} ({chars} chars)")
                    ok += 1
                else:
                    print(f"  empty document-{row.id}: {row.name[:60]} (no extractable text)")
            except Exception as exc:
                print(f"  FAIL document-{row.id}: {row.name[:40]} — {exc}")
        print(f"Done. Extracted text for {ok}/{len(rows)}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
