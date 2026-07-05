"""Auto-generate and store PNG previews for DWG drawings (search/vision only)."""

from __future__ import annotations



import logging

from typing import Optional



from app.core.config import settings

from app.storage.blob_access import is_blob_url

from app.storage.drawing_blob import blob_name_for_drawing, upload_drawing_bytes_to_blob

from app.storage.drawing_paths import DRAWING_CACHE_DIR, preview_cache_path

from app.storage.dwg_preview import convert_dwg_bytes_to_png



logger = logging.getLogger(__name__)





def ensure_dwg_preview_png(

    drawing,

    dwg_content: bytes,

    *,

    db=None,

    force: bool = False,

) -> Optional[bytes]:

    """

    Ensure a PNG preview exists for a DWG drawing.

    - Keeps original DWG in file_url

    - Stores PNG in local cache and preview_url (blob) for search/vision

    """

    if (drawing.file_type or "").upper() != "DWG":

        return None



    if not force and drawing.preview_url and is_blob_url(drawing.preview_url):

        from app.storage.blob_access import fetch_blob_bytes



        try:

            content, _ = fetch_blob_bytes(drawing.preview_url)

            return content

        except Exception:

            pass



    cache = preview_cache_path(drawing.drawing_no)

    if not force and cache.is_file():

        png = cache.read_bytes()

    else:

        try:

            png = convert_dwg_bytes_to_png(dwg_content)

        except Exception as exc:

            logger.warning("Auto DWG→PNG failed for %s: %s", drawing.drawing_no, exc)

            return None

        DRAWING_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        cache.write_bytes(png)

        logger.info("Generated preview PNG for %s (%s bytes)", drawing.drawing_no, len(png))



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


