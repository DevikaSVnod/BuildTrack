"""
Benchmark drawing inventory accuracy against golden expectations.

Usage (from backend/):
  py -3.10 scripts/benchmark_drawing_accuracy.py
  py -3.10 scripts/benchmark_drawing_accuracy.py --drawing-no AR-005-B
  py -3.10 scripts/benchmark_drawing_accuracy.py --reextract
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
from app.search.inventory_validate import validate_inventory
from app.search.object_inventory import extract_object_inventory, lookup_count, parse_inventory_json
from app.storage.drawing_raster import ensure_drawing_raster_bytes

# Golden ranges from validated POC test cases (adjust as ground truth is confirmed).
GOLDEN = [
    {
        "drawing_no": "AR-005-B",
        "element": "chair",
        "min": 5,
        "max": 7,
        "label": "office workstations",
    },
    {
        "drawing_no": "AR-005-B",
        "element": "desk",
        "min": 5,
        "max": 7,
        "label": "office desks",
    },
    {
        "drawing_no": "CI-003-C",
        "element": "chair",
        "min": 18,
        "max": 24,
        "label": "conference chairs (table + wall rows)",
    },
    {
        "drawing_no": "ST-009-B",
        "element": "bed",
        "min": 2,
        "max": 8,
        "label": "residential beds",
    },
    {
        "drawing_no": "AM-789-C",
        "element": "buildings",
        "min": 4,
        "max": 12,
        "label": "site buildings",
    },
    {
        "drawing_no": "AM-789-C",
        "element": "grading control point",
        "min": 20,
        "max": 80,
        "label": "GCP markers",
    },
]


def load_inventory(db, drawing: EngineeringDrawing, reextract: bool) -> dict | None:
    if reextract:
        content, content_type = ensure_drawing_raster_bytes(drawing, db=db)
        return extract_object_inventory(content, content_type, use_tiling=True)
    raw = getattr(drawing, "object_inventory", None)
    inv = parse_inventory_json(raw) if raw else None
    if inv:
        return inv
    content, content_type = ensure_drawing_raster_bytes(drawing, db=db)
    return extract_object_inventory(content, content_type, use_tiling=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark drawing inventory accuracy")
    parser.add_argument("--drawing-no", help="Run only one drawing number")
    parser.add_argument(
        "--reextract",
        action="store_true",
        help="Re-run vision extraction (slow; uses API)",
    )
    args = parser.parse_args()

    ensure_drawing_file_columns()
    db = SessionLocal()
    cases = GOLDEN
    if args.drawing_no:
        cases = [c for c in GOLDEN if c["drawing_no"].upper() == args.drawing_no.upper()]
        if not cases:
            print(f"No golden cases for {args.drawing_no}")
            return 1

    passed = 0
    failed = 0
    skipped = 0

    print(f"Running {len(cases)} golden check(s)" + (" [re-extract]" if args.reextract else "") + "...")

    for case in cases:
        dno = case["drawing_no"]
        drawing = db.query(EngineeringDrawing).filter(EngineeringDrawing.drawing_no == dno).first()
        if not drawing:
            print(f"  SKIP {dno}: not in database")
            skipped += 1
            continue

        try:
            inv = load_inventory(db, drawing, args.reextract)
        except Exception as exc:
            print(f"  FAIL {dno} / {case['label']}: could not load inventory ({exc})")
            failed += 1
            continue

        if not inv or not inv.get("objects"):
            print(f"  FAIL {dno} / {case['label']}: empty inventory")
            failed += 1
            continue

        count = lookup_count(inv, case["element"])
        validation = inv.get("validation") or validate_inventory(inv)
        vscore = validation.get("score", "?")
        vstatus = validation.get("status", "?")
        method = inv.get("method", "?")

        if count is None:
            print(f"  FAIL {dno} / {case['label']}: {case['element']} not found (method={method})")
            failed += 1
            continue

        ok = case["min"] <= count <= case["max"]
        mark = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(
            f"  {mark} {dno} / {case['label']}: {case['element']}={count} "
            f"(expected {case['min']}-{case['max']}) method={method} validation={vstatus}/{vscore}"
        )
        issues = validation.get("issues") or []
        if issues:
            print(f"         issues: {'; '.join(issues[:4])}")

    db.close()
    total = passed + failed
    print(f"\nResult: {passed}/{total} passed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
