"""
Rebuild structured object inventory for existing drawings (no re-upload needed).

Usage (from backend/):
  py -3.10 scripts/rebuild_object_inventories.py
  py -3.10 scripts/rebuild_object_inventories.py --drawing-no AR-011-A
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
from app.search.object_inventory import (
    embed_inventory_in_notes,
    empty_inventory,
    extract_object_inventory,
    inventory_to_search_text,
)
from app.storage.drawing_blob import upload_drawing_crawl_sidecar
from app.storage.drawing_raster import ensure_drawing_raster_bytes


def rebuild_one(db, drawing: EngineeringDrawing) -> bool:
    """Process one drawing — always attempts rasterization + inventory (no silent skips)."""
    drawing_id = drawing.id
    drawing_no = drawing.drawing_no
    try:
        content, content_type = ensure_drawing_raster_bytes(
            drawing, db=db, force_preview=False
        )
    except Exception as exc:
        # Last resort: force regenerate preview (DWG/PDF)
        try:
            db.rollback()
            content, content_type = ensure_drawing_raster_bytes(
                drawing, db=db, force_preview=True
            )
        except Exception as exc2:
            print(f"  FAIL {drawing_no}: could not get image ({exc2})")
            try:
                db.rollback()
                inventory = empty_inventory(scene=f"unavailable ({drawing.file_type or 'unknown'})")
                inventory["limitations"] = str(exc2)
                drawing.object_inventory = json.dumps(inventory, ensure_ascii=False)
                db.commit()
            except Exception as db_exc:
                print(f"  warning could not save failure note for {drawing_no}: {db_exc}")
                try:
                    db.rollback()
                except Exception:
                    pass
            return False

    # Release DB connection before long vision calls (Azure SQL drops idle links)
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    inventory = extract_object_inventory(content, content_type, use_tiling=True)
    if not inventory:
        inventory = empty_inventory()
    if not inventory.get("objects"):
        inventory["limitations"] = (
            (inventory.get("limitations") or "")
            + " Vision returned no countable objects; inventory stored as empty."
        ).strip()
        print(
            f"  ok {drawing_no}: 0 types (empty inventory saved), "
            f"scene={inventory.get('scene')}"
        )
    else:
        print(
            f"  ok {drawing_no}: "
            f"{len(inventory.get('objects') or [])} types, scene={inventory.get('scene')}"
        )

    # Fresh session for write — original connection may have timed out
    write_db = SessionLocal()
    try:
        row = write_db.query(EngineeringDrawing).filter(
            EngineeringDrawing.id == drawing_id
        ).one()
        notes = row.sheet_notes or ""
        inv_text = inventory_to_search_text(inventory)
        if inv_text and "OBJECT INVENTORY (structured):" not in notes:
            notes = f"{notes.rstrip()}\n\n{inv_text}"
        notes = embed_inventory_in_notes(notes, inventory)
        row.sheet_notes = notes
        row.object_inventory = json.dumps(inventory, ensure_ascii=False)
        write_db.commit()
        try:
            upload_drawing_crawl_sidecar(row)
        except Exception as exc:
            print(f"  warning sidecar {drawing_no}: {exc}")
        return True
    except Exception as exc:
        print(f"  FAIL {drawing_no}: could not save inventory ({exc})")
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
        print(f"Rebuilding inventory for {len(rows)} drawing(s)...")
        ok = 0
        for row in rows:
            if rebuild_one(db, row):
                ok += 1
        print(f"Done. Updated {ok}/{len(rows)}.")
        if ok < len(rows):
            print(
                "Note: any FAIL rows were still written with an empty inventory + error note."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
