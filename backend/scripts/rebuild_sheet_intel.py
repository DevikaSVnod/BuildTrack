"""
Rebuild structured sheet intelligence (scale, views, dims, title block)
for existing drawings.

Usage (from backend/):
  py -3.10 scripts/rebuild_sheet_intel.py
  py -3.10 scripts/rebuild_sheet_intel.py --drawing-no AR-113-9
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal, ensure_drawing_file_columns
from app.models.operational import EngineeringDrawing
from app.search.drawing_sheet_intel import (
    embed_sheet_intel_in_notes,
    empty_sheet_intel,
    extract_drawing_sheet_intel,
    sheet_intel_to_search_text,
)
from app.storage.drawing_blob import upload_drawing_crawl_sidecar
from app.storage.drawing_raster import ensure_drawing_raster_bytes


def rebuild_one(db, drawing: EngineeringDrawing) -> bool:
    drawing_id = drawing.id
    drawing_no = drawing.drawing_no
    try:
        content, content_type = ensure_drawing_raster_bytes(
            drawing, db=db, force_preview=False
        )
    except Exception as exc:
        try:
            db.rollback()
            content, content_type = ensure_drawing_raster_bytes(
                drawing, db=db, force_preview=True
            )
        except Exception as exc2:
            print(f"  FAIL {drawing_no}: could not get image ({exc2})")
            return False

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    intel = extract_drawing_sheet_intel(content, content_type)
    if not intel:
        intel = empty_sheet_intel()

    print(
        f"  ok {drawing_no}: "
        f"scale={len(intel.get('scale') or [])}, "
        f"views={len(intel.get('views') or [])}, "
        f"dims={len(intel.get('key_dimensions') or [])}, "
        f"kind={intel.get('drawing_kind')}"
    )

    write_db = SessionLocal()
    try:
        row = write_db.query(EngineeringDrawing).filter(
            EngineeringDrawing.id == drawing_id
        ).one()
        notes = row.sheet_notes or ""
        intel_text = sheet_intel_to_search_text(intel)
        if intel_text and "SHEET INTEL (structured):" not in notes:
            notes = f"{notes.rstrip()}\n\n{intel_text}"
        notes = embed_sheet_intel_in_notes(notes, intel)
        row.sheet_notes = notes
        row.sheet_intel = json.dumps(intel, ensure_ascii=False)
        write_db.commit()
        try:
            upload_drawing_crawl_sidecar(row)
        except Exception as exc:
            print(f"  warning sidecar {drawing_no}: {exc}")
        return True
    except Exception as exc:
        print(f"  FAIL {drawing_no}: could not save ({exc})")
        try:
            write_db.rollback()
        except Exception:
            pass
        return False
    finally:
        write_db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drawing-no", default=None)
    args = parser.parse_args()

    ensure_drawing_file_columns()
    db = SessionLocal()
    try:
        q = db.query(EngineeringDrawing)
        if args.drawing_no:
            q = q.filter(EngineeringDrawing.drawing_no == args.drawing_no.strip())
        rows = q.order_by(EngineeringDrawing.id.desc()).all()
        print(f"Rebuilding sheet intel for {len(rows)} drawing(s)...")
        ok = 0
        for row in rows:
            if rebuild_one(db, row):
                ok += 1
        print(f"Done. Updated {ok}/{len(rows)}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
