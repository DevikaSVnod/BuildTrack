"""
Extract searchable text from uploaded documents (PDF / DOCX / XLSX / plain text).

Mirrors drawing sheet_notes: persist body_text so Q&A works even when blob RAG is delayed.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_MAX_CHARS = 80000


def _clean_text(text: str) -> str:
    text = (text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _truncate(text: str) -> str:
    text = _clean_text(text)
    if len(text) <= _MAX_CHARS:
        return text
    return text[:_MAX_CHARS].rstrip() + "\n\n[… truncated for indexing …]"


def extract_text_from_pdf(content: bytes) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.warning("pypdfium2 not installed — cannot extract PDF text")
        return ""

    try:
        doc = pdfium.PdfDocument(content)
    except Exception as exc:
        logger.warning("PDF open failed for text extraction: %s", exc)
        return ""

    parts: list[str] = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            try:
                tp = page.get_textpage()
                page_text = tp.get_text_bounded() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                parts.append(page_text.strip())
            if sum(len(p) for p in parts) >= _MAX_CHARS:
                break
    finally:
        doc.close()
    return _truncate("\n\n".join(parts))


def extract_text_from_docx(content: bytes) -> str:
    """Extract DOCX text via zip+XML (no python-docx required)."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml = zf.read("word/document.xml")
    except Exception as exc:
        logger.warning("DOCX open failed: %s", exc)
        return ""

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        logger.warning("DOCX XML parse failed: %s", exc)
        return ""

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras: list[str] = []
    for p in root.findall(".//w:p", ns):
        texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
        if texts:
            paras.append("".join(texts))
    return _truncate("\n".join(paras))


def extract_text_from_xlsx(content: bytes) -> str:
    """Best-effort XLSX text via shared strings + sheet XML."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in root.findall(".//m:si", ns):
                    texts = [t.text or "" for t in si.findall(".//m:t", ns)]
                    shared.append("".join(texts))

            rows_out: list[str] = []
            sheet_names = sorted(
                n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
            )
            for sheet in sheet_names[:5]:
                root = ET.fromstring(zf.read(sheet))
                ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for row in root.findall(".//m:row", ns):
                    cells: list[str] = []
                    for c in row.findall("m:c", ns):
                        v = c.find("m:v", ns)
                        if v is None or v.text is None:
                            continue
                        if c.attrib.get("t") == "s":
                            try:
                                cells.append(shared[int(v.text)])
                            except (ValueError, IndexError):
                                cells.append(v.text)
                        else:
                            cells.append(v.text)
                    if cells:
                        rows_out.append(" | ".join(cells))
                    if sum(len(r) for r in rows_out) >= _MAX_CHARS:
                        break
            return _truncate("\n".join(rows_out))
    except Exception as exc:
        logger.warning("XLSX extract failed: %s", exc)
        return ""


def extract_text_from_plain(content: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return _truncate(content.decode(enc))
        except UnicodeDecodeError:
            continue
    return _truncate(content.decode("utf-8", errors="ignore"))


def extract_document_body_text(
    *,
    content: bytes,
    file_type: str,
    filename: str = "",
) -> str:
    """Return plain searchable text for a document file."""
    if not content:
        return ""

    ft = (file_type or "").upper().lstrip(".")
    name = (filename or "").lower()
    if not ft and "." in name:
        ft = name.rsplit(".", 1)[-1].upper()

    if ft == "PDF" or name.endswith(".pdf"):
        return extract_text_from_pdf(content)
    if ft in {"DOCX", "DOC"} or name.endswith((".docx", ".doc")):
        return extract_text_from_docx(content)
    if ft in {"XLSX", "XLS"} or name.endswith((".xlsx", ".xls")):
        return extract_text_from_xlsx(content)
    if ft in {"TXT", "CSV", "MD", "LOG", "JSON"} or name.endswith(
        (".txt", ".csv", ".md", ".log", ".json")
    ):
        return extract_text_from_plain(content)

    # Sniff PDF/DOCX magic
    if content[:4] == b"%PDF":
        return extract_text_from_pdf(content)
    if content[:2] == b"PK":
        # zip-based office
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = zf.namelist()
                if "word/document.xml" in names:
                    return extract_text_from_docx(content)
                if any(n.startswith("xl/") for n in names):
                    return extract_text_from_xlsx(content)
        except Exception:
            pass

    return ""
