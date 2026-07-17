"""Generate placeholder file bytes and upload document records to Azure Blob."""
from __future__ import annotations

import io
import os
import uuid
import zipfile
from typing import Optional

from app.core.config import settings


def is_blob_url(file_url: Optional[str]) -> bool:
    if not file_url:
        return False
    return "blob.core.windows.net" in file_url.lower()


def _sanitize_pdf_text(text: str) -> str:
    return text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'")


def _escape_pdf_text(text: str) -> str:
    text = _sanitize_pdf_text(text)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_page_stream(title: str, lines: list[str], *, show_title: bool = True) -> str:
    ops = ["BT /F1 11 Tf"]
    if show_title and title:
        ops.append(f"72 750 Td ({_escape_pdf_text(title[:200])}) Tj")
    else:
        ops.append("72 750 Td () Tj")
    for line in lines:
        ops.append("0 -14 Td")
        text = _escape_pdf_text(line[:220]) if line else " "
        ops.append(f"({text}) Tj")
    ops.append("ET")
    return "\n".join(ops)


def _paginate_lines(lines: list[str], per_page: int = 42) -> list[list[str]]:
    if not lines:
        return [[]]
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)]


def minimal_pdf_bytes(title: str, lines: list[str]) -> bytes:
    """Single-page PDF with searchable text (no external deps)."""
    return multi_page_pdf_bytes(title, lines)


def multi_page_pdf_bytes(title: str, lines: list[str]) -> bytes:
    """Multi-page PDF with searchable text (no external deps)."""
    pages = _paginate_lines(lines)
    page_objs: list[bytes] = []
    content_objs: list[bytes] = []
    kids_refs: list[str] = []

    # Object 1 = catalog, 2 = pages, 3 = font, 4+ = page/content pairs
    font_obj_num = 3
    next_num = 4
    for idx, page_lines in enumerate(pages):
        page_obj_num = next_num
        content_obj_num = next_num + 1
        next_num += 2
        stream = _pdf_page_stream(title if idx == 0 else "", page_lines, show_title=idx == 0)
        stream_len = len(stream.encode("latin-1", errors="replace"))
        kids_refs.append(f"{page_obj_num} 0 R")
        page_objs.append(
            (
                f"{page_obj_num} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_obj_num} 0 R /Resources << /Font << /F1 {font_obj_num} 0 R >> >> >>\nendobj\n"
            ).encode()
        )
        content_objs.append(
            f"{content_obj_num} 0 obj\n<< /Length {stream_len} >>\nstream\n{stream}\nendstream\nendobj\n".encode(
                "latin-1", errors="replace"
            )
        )

    kids = " ".join(kids_refs)
    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>\nendobj\n".encode(),
        b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    for page_obj, content_obj in zip(page_objs, content_objs):
        objects.append(page_obj)
        objects.append(content_obj)
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for obj in objects:
        offsets.append(sum(len(p) for p in parts))
        parts.append(obj)
    xref_start = sum(len(p) for p in parts)
    parts.append(f"xref\n0 {len(objects) + 1}\n".encode())
    parts.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        parts.append(f"{off:010d} 00000 n \n".encode())
    parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode()
    )
    return b"".join(parts)


def minimal_xlsx_bytes(title: str, lines: list[str]) -> bytes:
    """Minimal valid .xlsx with one sheet (zip + OOXML, no openpyxl)."""
    shared = [title] + lines[:20]
    sst_items = "".join(f"<si><t>{_xml_escape(s)}</t></si>" for s in shared)
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared)}" uniqueCount="{len(shared)}">'
        f"{sst_items}</sst>"
    )
    rows = "".join(
        f'<row r="{i + 1}"><c r="A{i + 1}" t="s"><v>{i}</v></c></row>'
        for i in range(len(shared))
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{rows}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Summary" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
        zf.writestr("xl/sharedStrings.xml", shared_strings)
    return buf.getvalue()


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _bridge_expansion_site_plan_lines(project: str, document_id: int) -> list[str]:
    return [
        "Highway Bridge Expansion Project",
        f"Project: {project}",
        f"BuildTrack document ID: {document_id}",
        "Project Manager: Sarah Chen",
        "Location: Interstate I-95, Miami, Florida",
        "Budget: $45,000,000 | Progress: 62%",
        "Project Description: widening the bridge corridor, structural reinforcement, drainage upgrades, safety features.",
        "Work Status Summary:",
        "Structural Reinforcement - Completed (100%)",
        "Bridge Deck Expansion - In Progress (75%)",
        "Drainage and Utilities - In Progress (55%)",
        "Safety and Traffic Management - In Progress (40%)",
        "Site Inspection Report",
        "Inspection Date: April 18, 2025",
        "Inspector: Michael Rodriguez",
        "Key Findings:",
        "Concrete curing quality met project standards.",
        "Minor corrosion observed on temporary steel supports near Pier P-12.",
        "Drainage trench excavation delayed due to heavy rainfall.",
        "Traffic diversion signs require replacement.",
        "No major structural defects identified.",
        "Major Equipment:",
        "2 Tower Cranes, 3 Concrete Pumps, 5 Excavators, 8 Dump Trucks",
        "Key Materials:",
        "2,400 Tons Reinforcing Steel, 18,000 m3 Concrete, 12,000 Tons Asphalt, 32 Expansion Joints",
        "Project Risks:",
        "Weather delays, material supply disruptions, and traffic congestion.",
        "Upcoming Milestones:",
        "Deck Expansion Completion - Aug 15, 2025",
        "Drainage Completion - Sep 10, 2025",
        "Safety System Installation - Oct 05, 2025",
        "Final Inspection - Nov 20, 2025",
    ]


def _commercial_tower_floor_plans_lines(project: str, document_id: int) -> list[str]:
    return [
        "Commercial Tower Phase 2 - Floor Plans and Project Documentation",
        f"Project: {project}",
        f"BuildTrack document ID: {document_id}",
        "Project ID: BT-2024-CTR-002",
        "Location: 1200 Main Street, Houston, TX",
        "Client: Houston Downtown Development Authority",
        "Project Manager: Priya Nair",
        "Total Budget: $120,000,000 (USD)",
        "Overall Progress: 10%",
        "LEED Gold certification target.",
        "Total gross floor area for Phase 2: 580,000 square feet.",
        "Typical floor plate: 32,000 sq ft per floor.",
        "Parking Capacity: 450 vehicles across 4 levels.",
        "Elevator Count: 14 Passenger + 4 Service Elevators",
        "Typical Floor Space Program:",
        "Open Office Area 21,500 sq ft, 8 meeting rooms, Central Core with elevators and MEP.",
        "Parking Structure: 450 spaces including EV charging and ADA accessible parking.",
        "Project Team:",
        "Priya Nair - Project Manager",
        "James Whitfield - Structural Engineer",
        "Maria Gonzalez - Architect",
        "Kevin Chan - MEP Engineer",
        "Sarah Thompson - HSE Officer",
        "David Park - Procurement Lead",
        "Risk Register:",
        "Building permit delays, steel and material price escalation, subcontractor availability.",
        "Key Milestones:",
        "Building permit received - August 1, 2026",
        "Curtain wall subcontract awarded - July 1, 2026",
        "Construction start Floor 18 - September 1, 2026",
        "Prepared by: Priya Nair. Reviewed by: Anita Desai.",
    ]


def _document_body_lines(name: str, project: str, document_id: int) -> list[str]:
    """Searchable body text for demo documents; generic placeholder for others."""
    lower = name.lower()
    if "bridge expansion" in lower or ("site plan" in lower and "bridge" in lower):
        return _bridge_expansion_site_plan_lines(project, document_id)
    if "commercial tower" in lower and "floor plan" in lower:
        return _commercial_tower_floor_plans_lines(project, document_id)
    return [
        name,
        f"BuildTrack document ID: {document_id}",
        f"Project: {project}",
        "Upload or sync a real PDF, DOCX, or XLSX file for full-text search indexing.",
    ]


def generate_document_bytes(
    name: str,
    file_type: Optional[str],
    project_name: Optional[str],
    document_id: int,
) -> tuple[bytes, str]:
    """Return (file_bytes, content_type) for a document record."""
    ext = os.path.splitext(name)[1].lower()
    ftype = (file_type or ext.lstrip(".") or "txt").upper()
    project = project_name or "Unassigned project"

    lines = _document_body_lines(name, project, document_id)
    if ftype in ("PDF",) or ext == ".pdf":
        return minimal_pdf_bytes(name, lines), "application/pdf"
    if ftype in ("XLSX", "XLS") or ext in (".xlsx", ".xls"):
        return minimal_xlsx_bytes(name, lines), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ftype in ("DOCX", "DOC") or ext in (".docx", ".doc"):
        return minimal_pdf_bytes(name, lines), "application/pdf"
    body = "\n".join([name, *lines]).encode("utf-8")
    return body, "application/octet-stream"


def upload_bytes_to_blob(
    content: bytes,
    blob_name: str,
    content_type: str,
    *,
    document_id: int,
    project_id: Optional[int],
    original_filename: str,
) -> tuple[str, int]:
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not configured")
    from azure.storage.blob import BlobServiceClient, ContentSettings

    size = len(content)
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER)
    blob_client = container_client.get_blob_client(blob_name)
    metadata = {
        "original_filename": original_filename,
        "document_id": str(document_id),
        "content_type": os.path.splitext(original_filename)[1].lstrip(".").upper() or "UNKNOWN",
        "size_bytes": str(size),
    }
    if project_id is not None:
        metadata["project_id"] = str(project_id)
    blob_client.upload_blob(
        content,
        overwrite=True,
        metadata=metadata,
        content_settings=ContentSettings(content_type=content_type),
    )
    return blob_client.url, size


def blob_name_for_document(document_id: int, filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_")
    return f"{uuid.uuid4()}_{safe}"


def delete_document_blob(file_url: str) -> None:
    """Remove a document blob when the SQL row is deleted."""
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not is_blob_url(file_url):
        return
    from urllib.parse import unquote, urlparse

    from azure.storage.blob import BlobServiceClient

    parsed = urlparse(file_url)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) < 2:
        return
    container, blob_name = path_parts[0], unquote(path_parts[1])
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
    blob_client.delete_blob()
