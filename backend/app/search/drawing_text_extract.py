"""
Extract searchable text from engineering drawing files (not hardcoded catalog text).

- PNG/JPG: Azure OpenAI vision OCR at index/sync time
- DWG: embedded text strings from the binary file
- User notes: preserved via USER_NOTES_MARKER when re-indexing
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

USER_NOTES_MARKER = "\n---USER NOTES---\n"

_IMAGE_TYPES = frozenset({"PNG", "JPG", "JPEG", "WEBP", "GIF"})

_DWG_NOISE = re.compile(
    r"^(?:\d+|[\W\d]+|AC\d+|G:[\w]+|[?]{1,3}[\w]*)$",
    re.I,
)


def split_stored_notes(combined: Optional[str]) -> tuple[str, str]:
    """Return (auto_extracted, user_notes) from stored sheet_notes."""
    text = (combined or "").strip()
    if USER_NOTES_MARKER in text:
        auto, user = text.split(USER_NOTES_MARKER, 1)
        return auto.strip(), user.strip()
    return text, ""


def combine_stored_notes(extracted: str, user_notes: Optional[str] = None) -> str:
    extracted = (extracted or "").strip()
    user = (user_notes or "").strip()
    if extracted and user:
        return f"{extracted}{USER_NOTES_MARKER}{user}"
    if user:
        return user
    return extracted


def _flatten_extracted_text(value: object) -> str:
    """Normalize vision JSON (string, dict of lists, etc.) to plain searchable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            heading = str(key).strip().upper().replace("_", " ")
            if isinstance(item, list):
                body = "\n".join(f"- {x}" for x in item if str(x).strip())
            else:
                body = str(item).strip()
            if body:
                lines.append(f"{heading}:\n{body}")
        return "\n\n".join(lines).strip()
    if isinstance(value, list):
        return "\n".join(f"- {x}" for x in value if str(x).strip()).strip()
    return str(value).strip()


def _data_url(content: bytes, content_type: str) -> str:
    mime = content_type if content_type.startswith("image/") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def extract_text_from_image(content: bytes, content_type: str = "image/png") -> str:
    """OCR / transcription from a drawing image using vision deployment."""
    deployment = settings.AZURE_OPENAI_VISION_DEPLOYMENT
    if not deployment or not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_KEY:
        logger.warning("Vision deployment not configured — skipping image text extraction")
        return ""

    prompt = (
        "Analyze this engineering drawing image for search indexing.\n"
        "1) Transcribe ALL readable text: title block, drawing number, revision, dimensions, "
        "labels, grid references, room names, schedules, notes, and annotations.\n"
        "2) If text is sparse (e.g. CAD floor plan with symbols), describe visible LAYOUT "
        "elements: rooms, furniture (beds, desks, chairs, sofas), bathroom fixtures "
        "(toilet, sink, shower), doors, stairs, and circulation. "
        "For furniture, count each chair/desk/table symbol and state subtotals per area.\n"
        "Organize under headings such as TITLE BLOCK, LABELS, DIMENSIONS, LAYOUT ELEMENTS, NOTES.\n"
        "Describe only what is visible. Do not invent values.\n"
        'Return JSON: {"extracted_text": "plain text string with all transcribed content"}'
    )

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        image_part = {"type": "image_url", "image_url": {"url": _data_url(content, content_type)}}
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        image_part,
                    ],
                }
            ],
            max_tokens=2000,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        payload = json.loads(raw)
        text = _flatten_extracted_text(payload.get("extracted_text"))
        if not text:
            text = _flatten_extracted_text(payload)
        if text:
            return text

        # Some CAD PNGs return empty JSON — plain vision call is more reliable for layout.
        fallback_prompt = (
            "Describe this engineering drawing for search indexing. "
            "List visible rooms, furniture, fixtures, doors, stairs, dimensions, and labels. "
            "Plain text only."
        )
        resp2 = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": fallback_prompt},
                        image_part,
                    ],
                }
            ],
            max_tokens=2000,
            temperature=0.0,
        )
        return (resp2.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Vision text extraction failed: %s", exc)
        return ""


def extract_text_from_dwg(content: bytes) -> str:
    """Pull embedded ASCII strings from a DWG binary (limited but file-derived)."""
    strings = re.findall(rb"[\x20-\x7e]{5,}", content)
    seen: set[str] = set()
    lines: list[str] = []
    for raw in strings:
        try:
            s = raw.decode("ascii", errors="ignore").strip()
        except Exception:
            continue
        if len(s) < 5 or _DWG_NOISE.match(s):
            continue
        if not re.search(r"[A-Za-z]", s):
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(s)
        if len(lines) >= 120:
            break

    if not lines:
        return ""
    return "EMBEDDED DWG STRINGS:\n" + "\n".join(f"- {ln}" for ln in lines)


def extract_drawing_sheet_notes(
    *,
    content: bytes,
    file_type: str,
    drawing_no: str,
    title: str,
    discipline: Optional[str] = None,
    user_notes: Optional[str] = None,
    existing_notes: Optional[str] = None,
    preview_content: Optional[bytes] = None,
    preview_content_type: str = "image/png",
) -> str:
    """
    Build searchable sheet_notes from the actual file bytes.
    Preserves user notes from upload (via marker) across re-index runs.
    """
    _, preserved_user = split_stored_notes(existing_notes)
    user = (user_notes or preserved_user or "").strip()

    ft = (file_type or "PNG").upper()
    extracted = ""
    if ft in _IMAGE_TYPES:
        mime = "image/png" if ft == "PNG" else f"image/{ft.lower()}"
        extracted = extract_text_from_image(content, mime)
    elif ft == "DWG":
        vision_text = ""
        if preview_content:
            vision_text = extract_text_from_image(preview_content, preview_content_type)
        if vision_text:
            extracted = vision_text
        else:
            extracted = extract_text_from_dwg(content)

    header = f"Drawing {drawing_no}: {title}"
    if discipline:
        header += f" ({discipline})"

    if extracted:
        body = f"{header}\n\n{extracted}"
    else:
        body = (
            f"{header}\n\n"
            f"No text could be automatically extracted from this {ft} file. "
            "Add layout notes when uploading, or export a PNG/PDF for richer indexing."
        )

    return combine_stored_notes(body, user)
