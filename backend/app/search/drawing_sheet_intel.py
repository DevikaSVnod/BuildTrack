"""
Structured sheet intelligence for engineering drawings.

At upload: GPT vision extracts scale, units, views (2D/3D/isometric/section…),
title-block fields, key dimensions, and notes summary → JSON on the drawing.
At ask time: answer scale / length / view / title-block questions from that
JSON first (before live vision).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

SHEET_INTEL_MARKER = "\n---SHEET INTEL---\n"

_VIEW_ALIASES = {
    "iso": "isometric",
    "isometric view": "isometric",
    "3d": "isometric",
    "3-d": "isometric",
    "orthographic": "2d orthographic",
    "ortho": "2d orthographic",
    "plan": "plan",
    "plan view": "plan",
    "elevation": "elevation",
    "section": "section",
    "sectional": "section",
    "perspective": "perspective",
    "end view": "end view",
    "side view": "side view",
    "front view": "front view",
}


def _vision_ready() -> bool:
    return bool(
        settings.AZURE_OPENAI_VISION_DEPLOYMENT
        and settings.AZURE_OPENAI_ENDPOINT
        and settings.AZURE_OPENAI_KEY
    )


def _client():
    from openai import AzureOpenAI

    return AzureOpenAI(
        api_key=settings.AZURE_OPENAI_KEY,
        api_version="2024-02-01",
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    )


def _data_url(content: bytes, content_type: str) -> str:
    mime = content_type or "image/png"
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


def empty_sheet_intel() -> dict[str, Any]:
    return {
        "drawing_kind": "unknown",
        "scale": [],
        "units": "",
        "views": [],
        "title_block": {},
        "key_dimensions": [],
        "notes_summary": [],
        "confidence": "low",
        "limitations": "",
        "method": "none",
    }


def extract_drawing_sheet_intel(
    content: bytes,
    content_type: str = "image/png",
) -> dict[str, Any]:
    """Vision pass: structured sheet metadata (scale, views, dims, title block)."""
    if not _vision_ready() or not content:
        return empty_sheet_intel()

    prompt = (
        "Analyze this engineering / architectural drawing sheet.\n"
        "Extract structured sheet intelligence (NOT furniture counts).\n\n"
        "Return JSON with:\n"
        '- drawing_kind: e.g. "mechanical assembly", "architectural floor-plan", '
        '"site plan", "detail", "unknown"\n'
        "- scale: array of {value, applies_to, source} e.g. "
        '{"value":"1:10","applies_to":"main views","source":"title_block"}\n'
        '- units: primary unit from title block / notes (e.g. "mm", "m")\n'
        "- views: array of {type, label, description} where type is one of: "
        "plan, elevation, section, isometric, perspective, end view, side view, "
        "front view, 2d orthographic, detail, other\n"
        "  Include ALL distinct views on the sheet.\n"
        "  IMPORTANT: a pictorial/3D-looking assembly drawing is type \"isometric\" "
        "(or \"perspective\" if vanishing-point perspective). Do not call that a plan.\n"
        "  Orthographic side/end cuts are elevation/section/end view — not isometric.\n"
        "- title_block: object with any of: product_name, drawing_no, revision, "
        "designed_by, drawn_by, weight, weight_unit, scale, units, size, date, other notes\n"
        "- key_dimensions: array of {label, value, unit, associated_part} for important "
        "annotated lengths/diameters/pitches/spans (copy numbers from dimension lines / notes). "
        "Examples: overall length 2000 mm, pitch 180, C-to-C 316.5, screw dia 180.\n"
        "- notes_summary: short bullet strings from NOTE / SPEC sections "
        "(motor RPM, sprocket ratio, chain number, etc.)\n"
        '- confidence: "high"|"medium"|"low"\n'
        '- limitations: what was unclear\n\n'
        "Do not invent numbers. If scale/units/views are not printed, omit or leave empty."
    )
    system = (
        "You extract engineering drawing sheet metadata: scale, units, view types "
        "(2D/3D/isometric/section/elevation), title block, and key dimensions. "
        "Return valid JSON only."
    )
    try:
        client = _client()
        image_payload: dict[str, Any] = {
            "url": _data_url(content, content_type),
            "detail": "high",
        }
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_VISION_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image_payload},
                    ],
                },
            ],
            max_tokens=1800,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        payload = json.loads(raw)
    except Exception as exc:
        logger.warning("Sheet intel extraction failed: %s", exc)
        return empty_sheet_intel()

    return _normalize_intel(payload)


def _normalize_intel(payload: dict[str, Any]) -> dict[str, Any]:
    out = empty_sheet_intel()
    if not isinstance(payload, dict):
        return out

    out["drawing_kind"] = str(payload.get("drawing_kind") or "unknown").strip() or "unknown"
    out["units"] = str(payload.get("units") or "").strip()
    out["confidence"] = str(payload.get("confidence") or "medium").lower()
    out["limitations"] = str(payload.get("limitations") or "").strip()
    out["method"] = "vision_sheet_intel"

    scales: list[dict[str, Any]] = []
    for row in payload.get("scale") or []:
        if isinstance(row, str) and row.strip():
            scales.append({"value": row.strip(), "applies_to": "", "source": ""})
            continue
        if not isinstance(row, dict):
            continue
        val = str(row.get("value") or "").strip()
        if not val:
            continue
        scales.append(
            {
                "value": val,
                "applies_to": str(row.get("applies_to") or "").strip(),
                "source": str(row.get("source") or "").strip(),
            }
        )
    out["scale"] = scales

    views: list[dict[str, Any]] = []
    for row in payload.get("views") or []:
        if not isinstance(row, dict):
            continue
        vtype = str(row.get("type") or "").strip().lower()
        if not vtype:
            continue
        views.append(
            {
                "type": vtype,
                "label": str(row.get("label") or "").strip(),
                "description": str(row.get("description") or "").strip(),
            }
        )
    out["views"] = views

    tb = payload.get("title_block") or {}
    if isinstance(tb, dict):
        out["title_block"] = {
            str(k): str(v).strip()
            for k, v in tb.items()
            if v is not None and str(v).strip()
        }
        if not out["units"] and out["title_block"].get("units"):
            out["units"] = out["title_block"]["units"]
        if not out["scale"] and out["title_block"].get("scale"):
            out["scale"] = [
                {
                    "value": out["title_block"]["scale"],
                    "applies_to": "title block",
                    "source": "title_block",
                }
            ]

    dims: list[dict[str, Any]] = []
    for row in payload.get("key_dimensions") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        value = row.get("value")
        if value is None or value == "":
            continue
        dims.append(
            {
                "label": label or "dimension",
                "value": value,
                "unit": str(row.get("unit") or out["units"] or "").strip(),
                "associated_part": str(row.get("associated_part") or "").strip(),
            }
        )
    out["key_dimensions"] = dims

    notes: list[str] = []
    for n in payload.get("notes_summary") or []:
        text = str(n or "").strip()
        if text:
            notes.append(text)
    out["notes_summary"] = notes
    return out


def sheet_intel_to_search_text(intel: Optional[dict[str, Any]]) -> str:
    if not intel or not isinstance(intel, dict):
        return ""
    if intel.get("method") in (None, "none") and not (
        intel.get("scale") or intel.get("views") or intel.get("key_dimensions")
    ):
        return ""

    lines = ["SHEET INTEL (structured):"]
    if intel.get("drawing_kind"):
        lines.append(f"Kind: {intel['drawing_kind']}")
    if intel.get("units"):
        lines.append(f"Units: {intel['units']}")
    for s in intel.get("scale") or []:
        if isinstance(s, dict) and s.get("value"):
            bit = f"Scale: {s['value']}"
            if s.get("applies_to"):
                bit += f" ({s['applies_to']})"
            lines.append(bit)
    if intel.get("views"):
        lines.append("Views:")
        for v in intel["views"]:
            if not isinstance(v, dict):
                continue
            line = f"- {v.get('type') or 'view'}"
            if v.get("label"):
                line += f" — {v['label']}"
            if v.get("description"):
                line += f": {v['description']}"
            lines.append(line)
    tb = intel.get("title_block") or {}
    if tb:
        lines.append("Title block:")
        for k, v in tb.items():
            lines.append(f"- {k}: {v}")
    if intel.get("key_dimensions"):
        lines.append("Key dimensions:")
        for d in intel["key_dimensions"]:
            if not isinstance(d, dict):
                continue
            line = f"- {d.get('label')}: {d.get('value')}"
            if d.get("unit"):
                line += f" {d['unit']}"
            if d.get("associated_part"):
                line += f" ({d['associated_part']})"
            lines.append(line)
    if intel.get("notes_summary"):
        lines.append("Notes:")
        for n in intel["notes_summary"]:
            lines.append(f"- {n}")
    return "\n".join(lines)


def embed_sheet_intel_in_notes(notes: str, intel: Optional[dict[str, Any]]) -> str:
    base = notes or ""
    if SHEET_INTEL_MARKER in base:
        base = base.split(SHEET_INTEL_MARKER, 1)[0].rstrip()
    useful = bool(
        intel
        and (
            intel.get("scale")
            or intel.get("views")
            or intel.get("key_dimensions")
            or intel.get("title_block")
            or intel.get("notes_summary")
        )
    )
    if not useful:
        return base
    payload = json.dumps(intel, ensure_ascii=False)
    return f"{base}{SHEET_INTEL_MARKER}{payload}"


def parse_sheet_intel_json(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and (
            data.get("scale") is not None
            or data.get("views") is not None
            or data.get("key_dimensions") is not None
            or data.get("title_block") is not None
        ):
            return data
    except json.JSONDecodeError:
        return None
    return None


def parse_sheet_intel_from_notes(notes: Optional[str]) -> Optional[dict[str, Any]]:
    text = notes or ""
    if SHEET_INTEL_MARKER not in text:
        return None
    raw = text.split(SHEET_INTEL_MARKER, 1)[1].strip()
    if "\n---" in raw:
        raw = raw.split("\n---", 1)[0].strip()
    return parse_sheet_intel_json(raw)


def resolve_drawing_sheet_intel(drawing: dict[str, Any]) -> Optional[dict[str, Any]]:
    meta = drawing.get("metadata") or {}
    inv = meta.get("sheet_intel")
    if isinstance(inv, dict):
        return inv
    if isinstance(inv, str):
        parsed = parse_sheet_intel_json(inv)
        if parsed:
            return parsed
    from_notes = parse_sheet_intel_from_notes(
        meta.get("sheet_notes") or drawing.get("snippet")
    )
    if from_notes:
        return from_notes
    try:
        from app.core.database import SessionLocal
        from app.models.operational import EngineeringDrawing

        drawing_no = (meta.get("drawing_no") or "").strip()
        drawing_id = meta.get("drawing_id")
        db = SessionLocal()
        try:
            q = db.query(EngineeringDrawing)
            row = None
            if drawing_no:
                row = q.filter(EngineeringDrawing.drawing_no == drawing_no).first()
            elif drawing_id is not None:
                row = q.filter(EngineeringDrawing.id == int(drawing_id)).first()
            if not row:
                return None
            col = getattr(row, "sheet_intel", None)
            parsed = parse_sheet_intel_json(col)
            if parsed:
                return parsed
            return parse_sheet_intel_from_notes(row.sheet_notes)
        finally:
            db.close()
    except Exception as exc:
        logger.debug("resolve_drawing_sheet_intel failed: %s", exc)
        return None


_SCALE_Q = re.compile(
    r"\b(scale|scaled|drawing\s+scale|what\s+scale|scale\s+of)\b",
    re.I,
)
_UNITS_Q = re.compile(r"\b(units?|millimet(?:er|re)s?|mm\b|metres?|meters?)\b", re.I)
_VIEW_Q = re.compile(
    r"\b(isometric|perspective|orthographic|ortho|2d|3d|3-d|"
    r"section(?:al)?|elevation|plan\s+view|end\s+view|side\s+view|front\s+view|"
    r"what\s+views?|which\s+views?|view\s+types?)\b",
    re.I,
)
_TITLE_Q = re.compile(
    r"\b(title\s+block|product\s+name|weight|revision|drawn\s+by|designed\s+by|"
    r"sheet\s+size|drawing\s+size)\b",
    re.I,
)
_DIM_Q = re.compile(
    r"\b(length|width|height|depth|diameter|dia\.?|pitch|span|dimension|"
    r"how\s+long|how\s+wide|how\s+tall|c\s*to\s*c|center\s*to\s*center|"
    r"overall|measurement|size\s+of)\b",
    re.I,
)
_NOTES_Q = re.compile(
    r"\b(notes?|spec(?:ification)?s?|motor\s+drive|sprocket\s+ratio|rpm)\b",
    re.I,
)


def is_sheet_intel_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    return bool(
        _SCALE_Q.search(q)
        or _VIEW_Q.search(q)
        or _TITLE_Q.search(q)
        or _DIM_Q.search(q)
        or (
            _UNITS_Q.search(q)
            and re.search(r"\b(what|which|drawing|sheet|unit)\b", q, re.I)
        )
        or (
            _NOTES_Q.search(q)
            and re.search(r"\b(what|list|tell|drawing|sheet|note)\b", q, re.I)
        )
    )


def format_sheet_intel_answer(
    query: str,
    intel: dict[str, Any],
    *,
    drawing_label: str = "",
) -> Optional[str]:
    """Build a deterministic answer from stored sheet intel for matching questions."""
    if not intel:
        return None
    q = (query or "").lower()
    prefix = f"On {drawing_label}, " if drawing_label else ""
    parts: list[str] = []
    limitations = str(intel.get("limitations") or "").strip()

    if _SCALE_Q.search(q):
        scales = intel.get("scale") or []
        if not scales:
            return None
        lines = []
        for s in scales:
            if not isinstance(s, dict) or not s.get("value"):
                continue
            line = str(s["value"])
            if s.get("applies_to"):
                line += f" ({s['applies_to']})"
            lines.append(line)
        if not lines:
            return None
        if len(lines) == 1:
            parts.append(f"**Answer:** {prefix}the drawing scale is **{lines[0]}**.")
        else:
            parts.append(f"**Answer:** {prefix}these scales are shown:")
            parts.append("**Scales:**\n" + "\n".join(f"- {ln}" for ln in lines))

    elif _VIEW_Q.search(q):
        views = intel.get("views") or []
        if not views:
            return None
        wanted = None
        for alias, canon in _VIEW_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", q):
                wanted = canon
                break
        matched = views
        specific_found = True
        if wanted:
            filtered = [
                v
                for v in views
                if isinstance(v, dict)
                and (
                    wanted in str(v.get("type") or "").lower()
                    or wanted in str(v.get("label") or "").lower()
                    or wanted in str(v.get("description") or "").lower()
                )
            ]
            if filtered:
                matched = filtered
            else:
                specific_found = False
                # Still show what views exist for context
                matched = views
        lines = []
        for v in matched:
            if not isinstance(v, dict):
                continue
            line = str(v.get("type") or "view")
            if v.get("label"):
                line += f" — {v['label']}"
            if v.get("description"):
                line += f": {v['description']}"
            lines.append(line)
        if not lines and not wanted:
            return None
        if wanted and not specific_found:
            parts.append(
                f"**Answer:** {prefix}no **{wanted}** view was identified on the sheet."
            )
            if lines:
                parts.append(
                    "**Views found instead:**\n" + "\n".join(f"- {ln}" for ln in lines)
                )
        elif wanted and specific_found:
            parts.append(
                f"**Answer:** {prefix}yes — the sheet includes a **{wanted}** view."
            )
            parts.append("**Views:**\n" + "\n".join(f"- {ln}" for ln in lines))
        else:
            parts.append(f"**Answer:** {prefix}the sheet shows these views:")
            parts.append("**Views:**\n" + "\n".join(f"- {ln}" for ln in lines))

    elif _TITLE_Q.search(q):
        tb = intel.get("title_block") or {}
        if not tb:
            return None
        focus_map = [
            (r"\bweight\b", "weight"),
            (r"\bproduct\b", "product_name"),
            (r"\brevision\b", "revision"),
            (r"\bdrawn\s+by\b", "drawn_by"),
            (r"\bdesigned\s+by\b", "designed_by"),
            (r"\b(sheet|drawing)\s+size\b", "size"),
        ]
        focused = None
        for pat, key in focus_map:
            if re.search(pat, q):
                focused = key
                break
        if focused and tb.get(focused):
            val = tb[focused]
            if focused == "weight" and tb.get("weight_unit"):
                val = f"{val} {tb['weight_unit']}"
            parts.append(
                f"**Answer:** {prefix}**{focused.replace('_', ' ')}** is **{val}**."
            )
        else:
            parts.append(f"**Answer:** {prefix}title block details:")
            parts.append(
                "**Title block:**\n"
                + "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in tb.items())
            )

    elif _DIM_Q.search(q):
        dims = intel.get("key_dimensions") or []
        if not dims:
            return None
        tokens = [
            t
            for t in re.findall(r"[a-z0-9]+", q)
            if len(t) > 2
            and t
            not in {
                "what",
                "which",
                "how",
                "long",
                "wide",
                "tall",
                "many",
                "the",
                "drawing",
                "length",
                "width",
                "height",
                "dimension",
                "size",
            }
        ]
        scored: list[tuple[int, dict[str, Any]]] = []
        for d in dims:
            if not isinstance(d, dict):
                continue
            hay = " ".join(
                [str(d.get("label") or ""), str(d.get("associated_part") or "")]
            ).lower()
            hits = sum(1 for t in tokens if t in hay)
            scored.append((hits, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        best_hits = scored[0][0] if scored else 0
        if best_hits > 0:
            chosen = [d for h, d in scored if h == best_hits]
        else:
            chosen = [d for _, d in scored]
        if not chosen:
            return None
        if len(chosen) == 1:
            d = chosen[0]
            val = f"{d.get('value')}"
            if d.get("unit"):
                val += f" {d['unit']}"
            label = d.get("label") or "dimension"
            part = d.get("associated_part") or ""
            extra = f" ({part})" if part else ""
            parts.append(
                f"**Answer:** {prefix}**{label}** is **{val}**{extra}."
            )
        else:
            parts.append(f"**Answer:** {prefix}key dimensions on the sheet:")
            lines = []
            for d in chosen:
                line = f"{d.get('label')}: {d.get('value')}"
                if d.get("unit"):
                    line += f" {d['unit']}"
                if d.get("associated_part"):
                    line += f" ({d['associated_part']})"
                lines.append(line)
            parts.append("**Dimensions:**\n" + "\n".join(f"- {ln}" for ln in lines))

    elif _UNITS_Q.search(q) and intel.get("units"):
        parts.append(
            f"**Answer:** {prefix}the drawing units are **{intel['units']}**."
        )

    elif _NOTES_Q.search(q) and intel.get("notes_summary"):
        parts.append(f"**Answer:** {prefix}notes / specs on the sheet:")
        parts.append(
            "**Notes:**\n" + "\n".join(f"- {n}" for n in intel["notes_summary"])
        )

    else:
        if not is_sheet_intel_query(query):
            return None
        overview: list[str] = []
        if intel.get("drawing_kind"):
            overview.append(f"kind: {intel['drawing_kind']}")
        if intel.get("scale"):
            overview.append(
                "scale: "
                + ", ".join(
                    str(s.get("value"))
                    for s in intel["scale"]
                    if isinstance(s, dict) and s.get("value")
                )
            )
        if intel.get("units"):
            overview.append(f"units: {intel['units']}")
        if intel.get("views"):
            overview.append(
                "views: "
                + ", ".join(
                    str(v.get("type"))
                    for v in intel["views"]
                    if isinstance(v, dict) and v.get("type")
                )
            )
        if not overview:
            return None
        parts.append(
            f"**Answer:** {prefix}sheet summary — " + "; ".join(overview) + "."
        )

    if limitations:
        parts.append(f"**Note:** {limitations}")
    parts.append("*Source: structured sheet intelligence (upload-time analysis).*")
    return "\n\n".join(parts)


def answer_from_stored_sheet_intel(
    *,
    query: str,
    drawing: dict[str, Any],
) -> Optional[str]:
    if not is_sheet_intel_query(query):
        return None
    intel = resolve_drawing_sheet_intel(drawing)
    if not intel:
        return None
    meta = drawing.get("metadata") or {}
    label = (meta.get("drawing_no") or "").strip() or (
        drawing.get("title") or ""
    ).strip()
    return format_sheet_intel_answer(query, intel, drawing_label=label)
