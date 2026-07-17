"""Ensure any drawing has raster bytes for vision / object inventory."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings
from app.storage.drawing_blob import blob_name_for_drawing, upload_drawing_bytes_to_blob
from app.storage.drawing_content import resolve_drawing_file_bytes, resolve_drawing_image_bytes
from app.storage.drawing_paths import DRAWING_CACHE_DIR, preview_cache_path
from app.storage.drawing_preview import ensure_dwg_preview_png

if TYPE_CHECKING:
    from app.models.operational import EngineeringDrawing

logger = logging.getLogger(__name__)


def sniff_file_type(content: bytes, declared: str = "", filename: str = "") -> str:
    """Detect real file type from magic bytes (DB/filename can be wrong)."""
    head = content[:16] if content else b""
    if head.startswith(b"%PDF"):
        return "PDF"
    # AutoCAD DWG versions look like AC10xx
    if len(head) >= 4 and head.startswith(b"AC"):
        return "DWG"
    if head.startswith(b"\x89PNG"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPG"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if head.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return "WEBP"

    declared = (declared or "").upper()
    if declared in {"PNG", "JPG", "JPEG", "WEBP", "GIF", "DWG", "PDF"}:
        return "JPG" if declared == "JPEG" else declared

    from app.storage.drawing_content import guess_file_type

    return guess_file_type(filename, "", fallback=declared or "PNG")


def _pdf_first_page_png(pdf_content: bytes) -> bytes:
    """Rasterize the first PDF page to PNG (pypdfium2, then PyMuPDF fallback)."""
    errors: list[str] = []

    try:
        import io

        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_content)
        try:
            if len(doc) < 1:
                raise RuntimeError("PDF has no pages")
            page = doc[0]
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
        finally:
            doc.close()
    except Exception as pdfium_exc:
        errors.append(f"pypdfium2: {pdfium_exc}")

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_content, filetype="pdf")
        try:
            if doc.page_count < 1:
                raise RuntimeError("PDF has no pages")
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            return pix.tobytes("png")
        finally:
            doc.close()
    except Exception as fitz_exc:
        errors.append(f"PyMuPDF: {fitz_exc}")

    raise RuntimeError("PDF to PNG failed — " + "; ".join(errors))


def _persist_preview_png(drawing: "EngineeringDrawing", png: bytes, *, db=None) -> bytes:
    """Cache locally and upload preview_url when possible."""
    DRAWING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = preview_cache_path(drawing.drawing_no)
    cache.write_bytes(png)

    if drawing.id and settings.AZURE_STORAGE_CONNECTION_STRING:
        preview_name = blob_name_for_drawing(
            drawing.id, drawing.drawing_no, f"{drawing.drawing_no}_preview.png"
        )
        try:
            url, _ = upload_drawing_bytes_to_blob(
                png,
                preview_name,
                "image/png",
                drawing_id=drawing.id,
                drawing_no=drawing.drawing_no,
                project_id=drawing.project_id,
                original_filename=f"{drawing.drawing_no}_preview.png",
            )
            drawing.preview_url = url
            if db is not None:
                db.commit()
        except Exception as exc:
            logger.warning("Preview blob upload failed for %s: %s", drawing.drawing_no, exc)
    return png


def ensure_drawing_raster_bytes(
    drawing: "EngineeringDrawing",
    *,
    db=None,
    force_preview: bool = False,
) -> tuple[bytes, str]:
    """
    Always return image bytes for vision.

    Order: existing preview/raster → sniff real type → DWG/PDF convert.
    Raises FileNotFoundError / RuntimeError if conversion is impossible.
    """
    if not force_preview:
        existing = resolve_drawing_image_bytes(drawing)
        if existing:
            return existing

    content, content_type, filename = resolve_drawing_file_bytes(drawing)
    ft = sniff_file_type(content, declared=drawing.file_type or "", filename=filename)

    # Correct mislabeled rows (e.g. DWG uploaded as PDF)
    if drawing.file_type and drawing.file_type.upper() != ft:
        logger.warning(
            "Drawing %s file_type=%s but content is %s — using sniffed type",
            drawing.drawing_no,
            drawing.file_type,
            ft,
        )
        drawing.file_type = ft
        if db is not None:
            try:
                db.commit()
            except Exception:
                db.rollback()

    if ft in {"PNG", "JPG", "JPEG", "WEBP", "GIF"}:
        mime = content_type if content_type.startswith("image/") else f"image/{ft.lower()}"
        return content, mime

    if ft == "DWG":
        drawing.file_type = "DWG"
        png = ensure_dwg_preview_png(drawing, content, db=db, force=force_preview)
        if png:
            return png, "image/png"
        raise RuntimeError(
            f"Could not rasterize DWG {drawing.drawing_no}. Check aspose-cad installation."
        )

    if ft == "PDF":
        png = _pdf_first_page_png(content)
        _persist_preview_png(drawing, png, db=db)
        logger.info("Generated PDF preview PNG for %s (%s bytes)", drawing.drawing_no, len(png))
        return png, "image/png"

    raise RuntimeError(
        f"Unsupported drawing file type '{ft}' for {drawing.drawing_no}; "
        "upload PNG/JPG/PDF/DWG."
    )
