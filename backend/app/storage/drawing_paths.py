"""Local cache directory for generated DWG preview PNGs (not a drawing store)."""
from __future__ import annotations

from pathlib import Path

# Temp/cache only — uploaded drawings live in Azure Blob + SQL.
DRAWING_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "drawings"


def preview_cache_path(drawing_no: str) -> Path:
    return DRAWING_CACHE_DIR / f"{drawing_no}_preview.png"
