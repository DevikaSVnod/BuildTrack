"""Convert DWG bytes to PNG for search/vision (original DWG kept for download)."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.storage.drawing_paths import DRAWING_CACHE_DIR

logger = logging.getLogger(__name__)


def convert_dwg_bytes_to_png(dwg_content: bytes) -> bytes:
    """
    Rasterize a DWG to PNG using Aspose.CAD.
    Raises RuntimeError if conversion is unavailable or fails.
    """
    try:
        import aspose.cad as cad
        from aspose.cad.imageoptions import CadRasterizationOptions, PngOptions
    except ImportError as exc:
        raise RuntimeError(
            "aspose-cad is not installed — cannot auto-convert DWG to PNG"
        ) from exc

    tmp_dir = DRAWING_CACHE_DIR / "dwg_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    dwg_path = tmp_dir / f"{token}.dwg"
    png_path = tmp_dir / f"{token}.png"
    dwg_path.write_bytes(dwg_content)
    try:
        image = cad.Image.load(str(dwg_path.resolve()))
        png_options = PngOptions()
        raster = CadRasterizationOptions()
        raster.page_width = float(2400)
        raster.page_height = float(2400)
        raster.layouts = ["Model"]
        png_options.vector_rasterization_options = raster
        image.save(str(png_path.resolve()), png_options)
        if not png_path.is_file() or png_path.stat().st_size < 100:
            raise RuntimeError("DWG to PNG conversion produced an empty file")
        return png_path.read_bytes()
    except Exception as exc:
        raise RuntimeError(f"DWG to PNG conversion failed: {exc}") from exc
    finally:
        for path in (dwg_path, png_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove temp file %s", path)
