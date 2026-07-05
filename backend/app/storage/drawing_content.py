"""Load drawing file bytes from Azure Blob (upload-only — no local catalog)."""

from __future__ import annotations



import mimetypes

from typing import TYPE_CHECKING



from app.storage.blob_access import fetch_blob_bytes, is_blob_url



if TYPE_CHECKING:

    from app.models.operational import EngineeringDrawing





def resolve_drawing_file_bytes(drawing: "EngineeringDrawing") -> tuple[bytes, str, str]:

    """Return (content, content_type, filename) from the drawing's blob URL."""

    if not drawing.file_url or not is_blob_url(drawing.file_url):

        raise FileNotFoundError(

            f"Drawing {drawing.drawing_no} has no blob file. Upload it via the Drawings page."

        )

    content, content_type = fetch_blob_bytes(drawing.file_url)

    filename = drawing.file_url.rsplit("/", 1)[-1]

    return content, content_type, filename





def resolve_drawing_image_bytes(

    drawing: "EngineeringDrawing",

) -> tuple[bytes, str] | None:

    """

    Image bytes for vision (PNG/JPG). Uses preview_url for DWG, else main file if raster.

    """

    ft = (drawing.file_type or "").upper()



    if drawing.preview_url and is_blob_url(drawing.preview_url):

        content, content_type = fetch_blob_bytes(drawing.preview_url)

        return content, content_type



    from app.storage.drawing_paths import preview_cache_path



    cached = preview_cache_path(drawing.drawing_no)

    if cached.is_file():

        content = cached.read_bytes()

        mime = mimetypes.guess_type(cached.name)[0] or "image/png"

        return content, mime



    if ft in {"PNG", "JPG", "JPEG", "WEBP", "GIF"}:

        content, content_type, _ = resolve_drawing_file_bytes(drawing)

        return content, content_type



    return None





def guess_file_type(filename: str, content_type: str, fallback: str = "PNG") -> str:

    ext = filename.rsplit(".", 1)[-1].upper() if "." in filename else ""

    if ext in {"PNG", "JPG", "JPEG", "DWG", "PDF", "GIF", "WEBP"}:

        return ext if ext != "JPEG" else "JPG"

    if content_type and "image/png" in content_type:

        return "PNG"

    if content_type and "dwg" in content_type:

        return "DWG"

    guessed, _ = mimetypes.guess_type(filename)

    if guessed and guessed.startswith("image/"):

        return guessed.split("/")[-1].upper()

    return fallback


