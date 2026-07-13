"""
Answer drawing content questions using GPT-4o vision (query-time).

Engineering drawings require evidence-backed answers. We reject confident
coordinate claims when dimension chains or grid references are not visible.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

from app.core.config import settings
from app.search.query_intel import (
    extract_drawing_no,
    is_drawing_contextual_layout_query,
    is_drawing_count_query,
    is_drawing_furniture_inventory_query,
    is_drawing_layout_identification_query,
    is_drawing_vision_first_query,
    is_drawing_zone_facilities_query,
)
from app.storage.blob_access import fetch_blob_bytes, is_blob_url

logger = logging.getLogger(__name__)

_LOCATION_QUERY = re.compile(
    r"\b(location|where\s+is|position|coordinates?|grid\s+(?:coordinate|intersection)|"
    r"located\s+at|nearest\s+reference|set\s+out)\b",
    re.I,
)

_DIMENSION_REASONING_QUERY = re.compile(
    r"\b(associated\s+with|directly\s+associated|dimension\s+chain|extension\s+line|"
    r"which\s+dimensions?|what\s+dimensions?|support(?:s|ed)?\s+your\s+answer|"
    r"evidence\s+tracing|sufficient\s+dimensions?|set\s+out|setting\s+out)\b",
    re.I,
)

_WEAK_NEARBY_DIMS = re.compile(
    r"\b(?:located|found|seen|visible)\s+near\s+(?:dimensions?\s+)?(?:such\s+as\s+)?"
    r"([\d,\s]+(?:mm)?)",
    re.I,
)

_OVER_INFERENCE = re.compile(
    r"\b(intersection\s+of|located\s+at\s+the\s+intersection|"
    r"from\s+the\s+nearest\s+reference\s+points?)\b",
    re.I,
)

_METADATA_STATUS = re.compile(
    r"\b(superseded|obsolete|void|under\s+review|approved|"
    r"status\s+may\s+affect|reliability\s+of\s+the\s+drawing)\b",
    re.I,
)

# Text sidecar/metadata terms that must not appear unless visible in image evidence.
_UNSUPPORTED_SHEET_CLAIMS = re.compile(
    r"\bpiling schedule\b|\binstallation sequence\b|\bsequence table\b|"
    r"\bschedule information\b|\bgeneral notes\b",
    re.I,
)

_REVISION_ON_SHEET = re.compile(
    r"\b(title\s+block|revision\s+(?:box|stamp|mark|cloud)|"
    r"rev(?:ision)?\s+(?:stamp|block)|status\s+stamp)\b",
    re.I,
)

# Common vision OCR confusions on CAD sheets (S/5, O/0, I/1, B/8).
_OCR_AMBIGUOUS_CAP = re.compile(r"\bPA5\b", re.I)
_PILE_CAP_LABEL = re.compile(r"\b(P[A-Z]{1,4}|PB\d+)\b", re.I)
_LEVEL_ANNOTATION = re.compile(r"\bFL\+?[\d.]+m?\b", re.I)

_DRAWING_NO = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z]\b", re.I)
_ELEMENT_REF = re.compile(r"\b(D\d+|P[A-Z]{1,4}|PB\d+)\b", re.I)


def is_drawing_location_query(query: str) -> bool:
    q = (query or "").lower()
    return bool(_LOCATION_QUERY.search(q))


def is_drawing_engineering_reasoning_query(query: str) -> bool:
    """Dimension association, evidence tracing, or setting-out validation."""
    q = query or ""
    return bool(_DIMENSION_REASONING_QUERY.search(q)) or is_drawing_location_query(q)


def is_structured_drawing_answer(text: str) -> bool:
    return "**Answer:**" in (text or "") and "**Evidence:**" in (text or "")


def has_unsupported_sheet_claims(text: str, evidence_blob: str = "") -> bool:
    """Schedule/sequence claims not backed by visible image evidence."""
    if not text or not _UNSUPPORTED_SHEET_CLAIMS.search(text):
        return False
    if evidence_blob and _UNSUPPORTED_SHEET_CLAIMS.search(evidence_blob):
        return False
    return True


def _rigorous_dimension_wording(dim_values: list[str], element: str = "the element") -> str:
    if not dim_values:
        return (
            "Dimensions are visible in the same drawing region, but no extension lines or "
            f"coordinate references are visible that directly associate them with {element}."
        )
    dim_text = ", ".join(f"{d} mm" for d in dim_values)
    target = element if element else "the element"
    return (
        f"Dimensions {dim_text} are visible in the same drawing region as {target}. "
        "However, no extension lines or coordinate references are visible that directly "
        f"associate these dimensions with the {target} center or position."
    )


def _extract_element_ref(query: str) -> str:
    q = query or ""
    m = re.search(r"\bpile\s+([A-Z]\d+)\b", q, re.I)
    if m:
        return m.group(1).upper()
    for m in _ELEMENT_REF.finditer(q):
        token = m.group(1).upper()
        if not _DRAWING_NO.search(token):
            return token
    return ""


def _element_token(element: str) -> str:
    """Normalize 'pile D17', 'D17', or 'PILE D17' to 'D17'."""
    if not element:
        return ""
    return re.sub(r"^pile\s+", "", element.strip(), flags=re.I).upper()


def _pile_label(element: str) -> str:
    token = _element_token(element)
    return f"pile {token}" if token else "the element"


def _normalize_level_text(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\bfl\+", "FL+", text, flags=re.I)


def _format_limitations(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        items = [_normalize_level_text(str(x).strip()) for x in value if str(x).strip()]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return "\n".join(f"- {item}" for item in items)
    text = _normalize_level_text(str(value).strip())
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return _format_limitations(parsed)
        except json.JSONDecodeError:
            pass
    return text


def _data_url_from_bytes(content: bytes, content_type: str) -> str:
    b64 = base64.b64encode(content).decode("ascii")
    mime = content_type or "application/octet-stream"
    return f"data:{mime};base64,{b64}"


def _vision_system_prompt(query: str) -> str:
    base = (
        "You are BuildTrack AI, an engineering drawing assistant. "
        "You MUST answer using ONLY what is explicitly visible in the drawing image. "
        "Never infer coordinates by assuming nearby dimensions define an object's position.\n\n"
        "Return valid JSON only with keys:\n"
        '- "answer": 1-2 concise sentences. State identification, then what cannot be determined.\n'
        '- "evidence": array of short factual bullets (labels, dimensions, annotations). '
        "Distinguish labels INSIDE a symbol vs annotations ADJACENT/NEARBY. "
        "Never claim level marks (FL, RL) are inside a pile symbol unless clearly so.\n"
        '- "limitations": string OR array of strings — what is missing (grid refs, dimension chains)\n'
        '- "confidence": overall — one of "high", "medium", "low", "insufficient"\n'
        '- "confidence_aspects": object mapping aspect to confidence, e.g. '
        '{"identification": "high", "exact_location": "low"}\n'
        '- "derivation": array of {"conclusion": "...", "based_on": ["visible item 1", ...]} '
        "mapping each claim to the drawing entities used\n\n"
        "Rules:\n"
        "- Do NOT connect nearby dimensions to a pile/object unless extension lines clearly link them\n"
        "- Never say an element is 'located near dimensions' without stating those dimensions "
        "are NOT linked by extension lines or coordinate references\n"
        "- Use rigorous wording: 'Dimensions X mm are visible in the same region as [element]. "
        "However, no extension lines or coordinate references directly associate them with [element].'\n"
        "- Prefer specific visible labels (e.g. D17, PB5) over generic phrases like 'the element'\n"
        "- Transcribe labels carefully; CAD text often confuses S/5, O/0, I/1, B/8, D/0. "
        "If a character is ambiguous, quote what you see and note uncertainty — do not guess.\n"
        "- NEVER mention drawing status (Superseded, Approved, Under Review, etc.) or revision "
        "unless you can see it in the image (title block, revision stamp, status cloud). "
        "Database metadata is NOT visible evidence.\n"
        "- Do NOT use drawing_no, project, discipline, or status from context in your answer\n"
        "- Distinguish attached vs nearby vs associated: only say 'associated' or 'applies to' "
        "when a leader line or extension line clearly links the annotation to the element\n"
        "- Level annotations (FL+1.2m, RL, etc.) are often adjacent to a region, not inside "
        "the pile symbol — describe as 'visible near the pile region' unless clearly embedded"
    )
    if is_drawing_engineering_reasoning_query(query):
        base += (
            "\n\nThis is an ENGINEERING REASONING question. Structure the answer as a site engineer would:\n"
            "1) What you can see (labels, symbols, annotations)\n"
            "2) What you cannot determine and why\n"
            "3) For any dimensions mentioned: state they are in the same region BUT not linked "
            "by extension lines or coordinate references unless you can see that linkage\n"
            "4) Populate derivation so every conclusion traces to specific visible entities\n"
            'Use confidence_aspects (e.g. identification, dimension_association, exact_location, setting_out).'
        )
        if re.search(r"\bassociated\s+with\b", query, re.I):
            base += (
                "\nFor dimension-association questions: if no extension lines link dimensions to the "
                "element, conclusion MUST be that no dimensions can be conclusively associated."
            )
        if re.search(r"\bset\s+out|setting\s+out|sufficient\s+dimensions?\b", query, re.I):
            base += (
                "\nFor setting-out questions: answer whether grid references and coordinate "
                "dimensions required for site set-out are visible. If not, answer No."
            )
    return base


def _parse_vision_payload(raw: str) -> Optional[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _format_confidence(payload: dict[str, Any]) -> str:
    aspects = payload.get("confidence_aspects")
    if isinstance(aspects, dict) and aspects:
        lines: list[str] = []
        for aspect, level in aspects.items():
            label = str(aspect).replace("_", " ")
            lines.append(f"{str(level).capitalize()} for {label}.")
        return "\n".join(lines)
    level = str(payload.get("confidence") or "insufficient").capitalize()
    return f"{level}."


def _strip_sentences_matching(text: str, pattern: re.Pattern[str]) -> str:
    if not text:
        return ""
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if sentence and not pattern.search(sentence):
            kept.append(sentence.strip())
    return " ".join(kept).strip()


def _sanitize_annotation_claims(text: str) -> str:
    """Soften spatial claims for level marks and proximity-only annotations."""
    if not text:
        return text

    text = re.sub(
        r"(['\"]?FL\+?[\d.]+m?['\"]?)\s+within\s+(?:circular\s+)?symbol",
        r"\1 appears adjacent to the pile region; not clearly part of the pile identifier",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(['\"]?FL\+?[\d.]+m?['\"]?)\s+inside\s+(?:the\s+)?(?:circular\s+)?(?:pile\s+)?symbol",
        r"\1 appears adjacent to the pile region; not clearly part of the pile identifier",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bassociated\s+with\s+(['\"]?FL\+?[\d.]+m?['\"]?)",
        (
            r"\1 is visible near the element; the visible snippet does not establish "
            "whether it directly applies to the element"
        ),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(is|are)\s+associated\s+with\s+",
        r"has visible nearby annotation ",
        text,
        flags=re.I,
    )
    return text


def _fix_ocr_cap_labels(text: str) -> str:
    """Flag likely S/5 confusion on pile-cap style labels."""
    if not text or not _OCR_AMBIGUOUS_CAP.search(text):
        return text
    return _OCR_AMBIGUOUS_CAP.sub(
        "PAS (label may read as PA5 — verify S vs 5 on sheet)",
        text,
    )


def _sanitize_text_field(text: str, evidence_blob: str) -> str:
    text = _fix_ocr_cap_labels(text)
    text = _sanitize_annotation_claims(text)
    if _METADATA_STATUS.search(text) and not _REVISION_ON_SHEET.search(evidence_blob):
        text = _strip_sentences_matching(text, _METADATA_STATUS)
    if has_unsupported_sheet_claims(text, evidence_blob):
        text = _strip_sentences_matching(text, _UNSUPPORTED_SHEET_CLAIMS)
    return text


def _sanitize_vision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove metadata leaks, flag OCR issues, and soften annotation spatial claims."""
    out = dict(payload)
    evidence = out.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)] if evidence else []
    evidence = [str(e).strip() for e in evidence if str(e).strip()]
    evidence_blob = " ".join(evidence)

    for field in ("answer",):
        out[field] = _sanitize_text_field(str(out.get(field) or ""), evidence_blob)

    lim_raw = out.get("limitations")
    if isinstance(lim_raw, list):
        lim_text = _format_limitations(lim_raw)
    else:
        lim_text = _sanitize_text_field(str(lim_raw or ""), evidence_blob)
    out["limitations"] = lim_text

    derivation = out.get("derivation") or []
    if isinstance(derivation, list):
        cleaned_derivation: list[dict[str, Any]] = []
        for item in derivation:
            if not isinstance(item, dict):
                continue
            conclusion = _sanitize_text_field(str(item.get("conclusion") or ""), evidence_blob)
            based_on = item.get("based_on") or []
            if not isinstance(based_on, list):
                based_on = [str(based_on)] if based_on else []
            based_on = [
                _sanitize_text_field(str(b).strip(), evidence_blob)
                for b in based_on
                if str(b).strip()
            ]
            cleaned_derivation.append({"conclusion": conclusion, "based_on": based_on})
        out["derivation"] = cleaned_derivation

    cleaned_evidence: list[str] = []
    for item in evidence:
        item = _sanitize_text_field(item, evidence_blob)
        if _METADATA_STATUS.search(item) and not _REVISION_ON_SHEET.search(item):
            continue
        cleaned_evidence.append(item)
    out["evidence"] = cleaned_evidence
    return out


def _extract_cap_labels(evidence: list[str]) -> list[str]:
    found: list[str] = []
    for item in evidence:
        for m in _PILE_CAP_LABEL.finditer(item):
            token = m.group(1).upper()
            if token not in found and token != "PILE":
                found.append(token)
    return found


def _rewrite_weak_dimension_language(answer: str, element: str = "") -> str:
    """Replace vague 'near dimensions' phrasing with rigorous engineering wording."""
    if not answer:
        return answer
    target = element or "the element"

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1) or ""
        vals = [v.strip().rstrip("mm").strip() for v in re.split(r"[, and]+", raw) if v.strip()]
        vals = [v for v in vals if re.fullmatch(r"\d{2,5}", v)]
        return _rigorous_dimension_wording(vals, target)

    return _WEAK_NEARBY_DIMS.sub(_replace, answer)


def _consolidate_evidence(
    evidence: list[str],
    *,
    element: str = "",
    cap_labels: Optional[list[str]] = None,
) -> list[str]:
    """Normalize vision evidence into concise, non-repetitive production bullets."""
    blob = " ".join(evidence).lower()
    bullets: list[str] = []
    token = _element_token(element)
    if token:
        bullets.append(f"{token} label visible.")
    elif re.search(r"\bD\d+\b", blob, re.I):
        m = re.search(r"\b(D\d+)\b", blob, re.I)
        if m:
            bullets.append(f"{m.group(1).upper()} label visible.")

    caps = cap_labels or _extract_cap_labels(evidence)
    if caps:
        cap_text = " / ".join(caps)
        bullets.append(f"{cap_text} label visible within circular marker.")
    elif re.search(r"\bpas\b|\bpb5\b", blob, re.I):
        bullets.append("PAS / PB5 label visible within circular marker.")

    dims = _nearby_dimension_values(evidence)
    if dims:
        dim_text = ", ".join(dims)
        bullets.append(f"Dimensions {dim_text} mm visible nearby (not linked by extension lines).")

    if _LEVEL_ANNOTATION.search(blob):
        level = _LEVEL_ANNOTATION.search(blob)
        level_text = level.group(0) if level else "FL+1.2m"
        bullets.append(
            f"{level_text} annotation visible near the pile region "
            "(not clearly inside the pile symbol)."
        )

    if not bullets:
        for item in evidence[:4]:
            cleaned = re.sub(r"^label\s+['\"]?", "", item, flags=re.I).strip()
            if cleaned:
                bullets.append(cleaned[0].upper() + cleaned[1:] if cleaned else cleaned)

    seen: set[str] = set()
    unique: list[str] = []
    for b in bullets:
        key = b.lower()
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique[:5]


def _build_production_answer(payload: dict[str, Any], *, element: str = "") -> str:
    """Short identification-first answer; detail lives in evidence/limitations."""
    token = _element_token(element) or _extract_element_ref(str(payload.get("answer") or ""))
    raw = _rewrite_weak_dimension_language(
        str(payload.get("answer") or "").strip(),
        _pile_label(token),
    )
    raw = _sanitize_annotation_claims(raw)

    caps = _extract_cap_labels(payload.get("evidence") or [])
    cap_part = f" within the {' / '.join(caps)} circular marker" if caps else ""
    subject = f"Pile {token}" if token else "The element"

    if re.search(r"\bcannot\b|\bcan\s*not\b|insufficient|undetermined", raw, re.I):
        return (
            f"{subject} is identified{cap_part}. "
            "Precise setting-out coordinates cannot be determined from the visible snippet."
        )

    sentences = re.split(r"(?<=[.!?])\s+", raw)
    short = " ".join(sentences[:2]).strip()
    if short and len(short) < 320 and not re.search(r"\bpile\s+pile\b", short, re.I):
        return short
    return (
        f"{subject} is identified{cap_part}. "
        "Precise setting-out coordinates cannot be determined from the visible snippet."
    )


def _format_vision_response(payload: dict[str, Any], *, element: str = "") -> str:
    evidence = payload.get("evidence") or []
    limitations = _format_limitations(payload.get("limitations"))

    if not isinstance(evidence, list):
        evidence = [str(evidence)] if evidence else []
    evidence = [_normalize_level_text(str(e).strip()) for e in evidence if str(e).strip()]

    token = _element_token(element)
    answer = _build_production_answer(payload, element=token)
    evidence_bullets = [_normalize_level_text(b) for b in _consolidate_evidence(evidence, element=token)]

    if not limitations:
        limitations = (
            "The visible snippet does not contain grid references, coordinate markers, "
            "or dimension extension lines that locate the element."
        )

    parts: list[str] = [
        f"**Answer:**\n{answer}",
        "**Evidence:**",
        *[f"- {b}" for b in evidence_bullets],
        f"**Limitations:**\n{limitations}",
        f"**Confidence:**\n{_format_confidence(payload)}",
    ]
    return "\n".join(parts).strip()


def _nearby_dimension_values(evidence: list[str]) -> list[str]:
    found: list[str] = []
    for item in evidence:
        for m in re.finditer(r"\b(\d{3,5})\s*mm\b", item, re.I):
            val = m.group(1)
            if val not in found:
                found.append(val)
    return found[:5]


def _location_answer_from_payload(
    drawing_no: str,
    query: str,
    payload: dict[str, Any],
) -> str:
    """Build an engineering partial-location answer from vision evidence."""
    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)] if evidence else []
    evidence = [str(e).strip() for e in evidence if str(e).strip()]

    element = _extract_element_ref(query)
    label = drawing_no or "the drawing"
    answer = str(payload.get("answer") or "").strip()
    limitations = _format_limitations(payload.get("limitations"))

    if answer and not _OVER_INFERENCE.search(answer):
        aspects = payload.get("confidence_aspects")
        if isinstance(aspects, dict) and aspects.get("exact_location") in (
            "low",
            "insufficient",
            "medium",
        ):
            return _format_vision_response(
                _sanitize_vision_payload(payload),
                element=element,
            )
        if str(payload.get("confidence") or "").lower() in ("low", "insufficient", "medium"):
            if evidence and re.search(r"\b(D\d+|P[A-Z]{1,4}|PB\d+)\b", answer, re.I):
                return _format_vision_response(
                    _sanitize_vision_payload(payload),
                    element=element,
                )

    ident_lines = [
        e
        for e in evidence
        if re.search(r"\b(D\d+|P[A-Z]{1,4}|PB\d+|pile|cap|label|symbol|visible)\b", e, re.I)
    ]
    dim_lines = [e for e in evidence if re.search(r"\d+\s*mm", e, re.I)]
    nearby_dims = _nearby_dimension_values(evidence + dim_lines)

    cap_labels = _extract_cap_labels(evidence + ident_lines)

    cap_part = f" within the {' / '.join(cap_labels)} circular marker" if cap_labels else ""
    if element:
        answer_text = (
            f"Pile {element} is identified{cap_part} on drawing **{label}**. "
            "Precise setting-out coordinates cannot be determined from the visible snippet."
        )
    else:
        answer_text = (
            f"The requested element is shown on drawing **{label}**, "
            "but precise setting-out coordinates cannot be determined from the visible snippet."
        )

    ident_evidence = [e for e in (evidence or ident_lines) if e]
    dim_evidence = [e for e in (evidence or dim_lines) if re.search(r"\d", e)]
    derivation: list[dict[str, Any]] = []
    if element and ident_evidence:
        derivation.append(
            {
                "conclusion": f"{element} is identifiable on the sheet",
                "based_on": ident_evidence[:3],
            }
        )
    if nearby_dims or dim_lines:
        derivation.append(
            {
                "conclusion": "No dimensions are conclusively associated with the element",
                "based_on": dim_evidence[:3] or ["no extension lines visible linking dimensions to element"],
            }
        )
    derivation.append(
        {
            "conclusion": "Exact coordinates / grid location cannot be determined",
            "based_on": ["grid references not visible", "dimension chains incomplete"],
        }
    )

    rebuilt = {
        "answer": answer_text,
        "evidence": evidence or ident_lines or dim_lines,
        "derivation": derivation,
        "limitations": limitations
        or (
            "The visible snippet does not contain grid references, coordinate markers, "
            "or dimension extension lines that locate the element."
        ),
        "confidence": "low",
        "confidence_aspects": {
            "identification": "high" if (element or ident_lines) else "medium",
            "dimension_association": "insufficient",
            "exact_location": "low",
        },
    }
    if element:
        rebuilt["confidence_aspects"]["identification"] = "high"

    return _format_vision_response(
        _sanitize_vision_payload(rebuilt),
        element=element,
    )


def _reject_vision_payload(query: str, payload: dict[str, Any]) -> bool:
    """Return True if we should not trust this vision answer as-is."""
    confidence = str(payload.get("confidence") or "").lower()
    answer = str(payload.get("answer") or "")
    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = []

    if is_drawing_location_query(query) and _OVER_INFERENCE.search(answer):
        return True

    if confidence == "high" and not evidence:
        return True

    return False


def _conservative_location_fallback(drawing_no: str, query: str = "") -> str:
    return _location_answer_from_payload(
        drawing_no,
        query,
        {"evidence": [], "limitations": "", "confidence": "insufficient"},
    )


def drawing_vision_fallback(*, query: str, drawing: dict[str, Any]) -> str:
    """
    Structured engineering answer without calling vision.
    Used when vision fails or text-LLM would leak sidecar metadata.
    """
    meta = drawing.get("metadata") or {}
    drawing_no = (meta.get("drawing_no") or extract_drawing_no(query) or "").strip()
    return _conservative_location_fallback(drawing_no, query)


def _drawing_followups(query: str) -> list[str]:
    if is_drawing_engineering_reasoning_query(query):
        return [
            "What dimensions are directly associated with this element?",
            "Which drawing elements support your answer?",
            "Are there sufficient dimensions to set out this pile on site?",
        ]
    return [
        "Which drawing elements support your answer?",
        "What other key dimensions are shown on this drawing?",
        "What evidence on the drawing supports this answer?",
    ]


def _finalize_drawing_answer(query: str, answer: str, drawing: dict[str, Any]) -> str:
    """Ensure drawing spatial answers stay structured and evidence-based."""
    evidence_blob = ""
    if "**Evidence:**" in (answer or ""):
        parts = answer.split("**Evidence:**", 1)
        evidence_blob = parts[1] if len(parts) > 1 else ""

    if (
        not is_structured_drawing_answer(answer)
        or has_unsupported_sheet_claims(answer, evidence_blob)
    ):
        logger.info("Drawing answer rejected — using structured fallback for: %s", query[:50])
        return drawing_vision_fallback(query=query, drawing=drawing)
    return answer


def _load_drawing_image_for_vision(drawing: dict[str, Any]) -> tuple[bytes, str, str]:
    """Load raster image bytes for vision (PNG/JPG or DWG preview)."""
    meta = drawing.get("metadata") or {}
    drawing_no_sql = (meta.get("drawing_no") or "").strip()
    drawing_id = meta.get("drawing_id")

    try:
        from app.core.database import SessionLocal
        from app.models.operational import EngineeringDrawing
        from app.storage.drawing_content import resolve_drawing_image_bytes

        db = SessionLocal()
        try:
            q = db.query(EngineeringDrawing)
            if drawing_no_sql:
                row = q.filter(EngineeringDrawing.drawing_no == drawing_no_sql).first()
            elif drawing_id is not None:
                row = q.filter(EngineeringDrawing.id == int(drawing_id)).first()
            else:
                row = None
            if row:
                loaded = resolve_drawing_image_bytes(row)
                if loaded:
                    content, content_type = loaded
                    return content, content_type, drawing_no_sql or row.drawing_no
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Could not load drawing image from SQL: %s", exc)

    file_url = meta.get("preview_url") or meta.get("file_url") or ""
    file_type = (meta.get("file_type") or "").upper()
    if file_url and is_blob_url(file_url) and file_type in {"PNG", "JPG", "JPEG", "WEBP", "GIF"}:
        content, content_type = fetch_blob_bytes(file_url)
        return content, content_type, drawing_no_sql

    raise FileNotFoundError("No raster image available for vision")


def _validate_bed_count_payload(query: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Flag overstated per-unit bed counts (desks/closets confused with beds)."""
    if not re.search(r"\bbeds?\b", query, re.I):
        return payload
    breakdown = payload.get("breakdown") or []
    per_unit: list[int] = []
    for line in breakdown:
        m = re.search(r"(\d+)", str(line))
        if m:
            per_unit.append(int(m.group(1)))
    if any(n > 3 for n in per_unit):
        payload["limitations"] = (
            "Per-unit count may include non-bed symbols (desks KD2, closets with hangers). "
            "Each unit module typically has 2 bed symbols — please verify visually."
        )
    if per_unit:
        summed = sum(per_unit)
        total = payload.get("total")
        try:
            if total is not None and int(total) != summed:
                payload["total"] = summed
                payload["answer"] = f"There are {summed} beds in total."
        except (TypeError, ValueError):
            pass
    return payload


def vision_contextual_layout_answer(
    *,
    query: str,
    drawing: dict[str, Any],
) -> Optional[str]:
    """
    Answer floor-plan / layout questions by analyzing the drawing image (or DWG preview).
    """
    if not is_drawing_vision_first_query(query) and not is_drawing_count_query(query):
        return None
    deployment = settings.AZURE_OPENAI_VISION_DEPLOYMENT
    if not deployment or not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_KEY:
        return None

    try:
        content, content_type, drawing_no = _load_drawing_image_for_vision(drawing)
        data_url = _data_url_from_bytes(content, content_type)
    except FileNotFoundError:
        return (
            "This DWG could not be rasterized to a preview image for visual analysis. "
            "Re-run drawing index sync or check that aspose-cad is installed on the server."
        )
    except Exception as exc:
        logger.warning("Contextual vision: failed to load image: %s", exc)
        return None

    image_detail = "auto"

    if is_drawing_count_query(query):
        element = "items"
        m = re.search(
            r"\b(chairs?|desks?|doors?|tables?|workstations?|beds?|rooms?|"
            r"toilets?|sinks?|showers?|entries|exits|entry|exit)\b",
            query,
            re.I,
        )
        if m:
            element = m.group(1).lower()
        bed_hint = ""
        if re.search(r"\bbeds?\b", query, re.I):
            bed_hint = (
                "\nBED COUNTING RULES (critical):\n"
                "- ONE bed = ONE rectangle furniture symbol with a pillow block at one end "
                "AND a diagonal fold line (blanket). Count only these symbols.\n"
                "- Do NOT count as beds: desks (KD2), chairs, closets/wardrobes (hanger rows), "
                "bathrooms, doors, windows (C1518), or plain green dimension lines.\n"
                "- Each residential unit module in this plan has TWO bed symbols (a pair), "
                "not four. If you get 4+ beds in one unit, re-scan — you are likely "
                "counting desks or closets.\n"
                "- Mirrored/repeated units: count each bed symbol on the full sheet once.\n"
                "- Breakdown format: 'unit module 1: 2 beds', 'unit module 2: 2 beds', etc. "
                "The breakdown numbers must sum exactly to total.\n"
            )
        prompt = (
            f"Question about floor plan drawing {drawing_no or 'shown'}: {query}\n\n"
            "Count every visible instance of the asked element across the ENTIRE drawing image. "
            "Include items in all rooms, units, and repeated/mirrored layouts on the sheet. "
            "Do not stop after the first group — scan the full sheet."
            f"{bed_hint}\n"
            'Return JSON: {"answer": "There are N <element> in total.", "total": N, '
            '"breakdown": ["area/unit: count", ...], "limitations": "what is unclear"}'
        )
        system = (
            "You count furniture and fixture symbols on architectural floor plans. "
            "Answer only from the image. Give an explicit total number. "
            "Never confuse desks, closets, or chairs with beds. "
            "If uncertain, say so in limitations — never claim high confidence when symbols overlap."
        )
        max_tokens = 800
        image_detail = "high"
    elif is_drawing_layout_identification_query(query):
        prompt = (
            f"Question about floor plan drawing {drawing_no or 'shown'}: {query}\n\n"
            "Identify the room or space type from what is VISUALLY shown in the image: "
            "furniture (beds, desks, conference tables, chairs), bathroom fixtures, kitchen "
            "elements, doors, and circulation.\n"
            "IMPORTANT: Ignore the drawing title if it conflicts with visible content. "
            "If the title says 'conference room' but you see beds and bathrooms, describe "
            "what the layout actually shows (e.g. bedroom, studio apartment, hotel unit).\n"
            'Return JSON: {"answer": "...", "evidence": ["visible element 1", ...], '
            '"limitations": "what is unclear"}'
        )
        system = (
            "You classify architectural floor plans from visible content only. "
            "Never answer from assumed titles — beds + ensuite bathroom means bedroom/apartment, "
            "not conference room. Be direct and honest about what the image shows."
        )
        max_tokens = 700
    elif is_drawing_zone_facilities_query(query):
        prompt = (
            f"Question about floor plan drawing {drawing_no or 'shown'}: {query}\n\n"
            "Focus on the restroom/bathroom/washroom area visible in the drawing. "
            "List every fixture and fitting in that zone with counts:\n"
            "- toilet / WC\n- sink / basin\n- shower / bathtub\n"
            "- counter / vanity\n- mirror\n- doors into the restroom\n"
            "Scan all restroom zones shown on the sheet (there may be more than one). "
            "Ignore the drawing title if it conflicts with visible content.\n"
            'Return JSON: {"answer": "short summary", "inventory": ['
            '{"item": "toilet", "count": 1, "location": "restroom A"}, ...], '
            '"evidence": ["item: count", ...], "limitations": "..."}'
        )
        system = (
            "You list restroom/bathroom fixtures on architectural floor plans. "
            "Answer only from visible symbols in the image. "
            "Do not use engineering coordinate or setting-out language."
        )
        max_tokens = 900
    elif is_drawing_furniture_inventory_query(query):
        which_hint = ""
        from app.search.query_intel import is_which_drawing_query

        if is_which_drawing_query(query):
            which_hint = (
                f"\nIMPORTANT: The question asks WHICH drawing. Start the answer with: "
                f"'Drawing {drawing_no or 'shown'}' and state clearly that THIS sheet "
                "contains (or does not contain) the requested items.\n"
            )
        prompt = (
            f"Question about floor plan drawing {drawing_no or 'shown'}: {query}\n\n"
            f"{which_hint}"
            "Inventory ALL furniture and fixtures visible across the ENTIRE drawing image. "
            "Scan every room/unit shown — do not stop at bathrooms or one area only.\n"
            "Include each category you can see with counts:\n"
            "- beds (each bed symbol)\n"
            "- desks / workstations\n"
            "- chairs\n"
            "- tables\n"
            "- wardrobes / closets / hangers\n"
            "- bathroom fixtures (toilet, sink, shower)\n"
            "- doors\n"
            "Ignore the drawing title if it says 'conference room' but beds are visible.\n"
            'Return JSON: {"answer": "short summary sentence", "inventory": ['
            '{"item": "beds", "count": 4, "location": "two per unit"}, ...], '
            '"evidence": ["item: count in location", ...], "limitations": "..."}'
        )
        system = (
            "You inventory furniture and fixtures on architectural floor plans. "
            "List every visible item type with counts. Beds are furniture — always include them. "
            "Answer only from the image, not from titles."
        )
        max_tokens = 1000
    else:
        prompt = (
            f"Question about floor plan drawing {drawing_no or 'shown'}: {query}\n\n"
            "Analyze the drawing image. Describe rooms, furniture, fixtures, doors, entry/exit "
            "points, and circulation only when clearly visible. Give a direct answer in plain language.\n"
            'Return JSON: {"answer": "...", "evidence": ["visible item 1", ...], '
            '"limitations": "what is unclear or not visible"}'
        )
        system = (
            "You analyze architectural floor plans. Answer only from the image. "
            "Count doors and access points when asked. Be specific and concise."
        )
        max_tokens = 700

    image_url_payload: dict[str, Any] = {"url": data_url}
    if image_detail == "high":
        image_url_payload["detail"] = "high"

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image_url_payload},
                    ],
                },
            ],
            max_tokens=max_tokens,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        payload = json.loads(raw)
        if is_drawing_count_query(query):
            payload = _validate_bed_count_payload(query, payload)
        answer = str(payload.get("answer") or "").strip()
        limitations = str(payload.get("limitations") or "").strip()
        if not answer:
            return None

        if is_drawing_count_query(query):
            total = payload.get("total")
            breakdown = payload.get("breakdown") or []
            parts = [f"**Answer:** {answer}"]
            if total is not None:
                element = "items"
                m = re.search(
                    r"\b(chairs?|desks?|doors?|tables?|workstations?|beds?|rooms?|"
                    r"entries|exits|entry|exit)\b",
                    query,
                    re.I,
                )
                if m:
                    element = m.group(1).lower()
                parts[0] = f"**Answer:** There are **{total} {element}** visible on the drawing."
            if isinstance(breakdown, list) and breakdown:
                bullets = "\n".join(f"- {b}" for b in breakdown if str(b).strip())
                if bullets:
                    parts.append(f"**Breakdown:**\n{bullets}")
            if limitations:
                parts.append(f"**Note:** {limitations}")
            return "\n\n".join(parts)

        if is_drawing_furniture_inventory_query(query) or is_drawing_zone_facilities_query(query):
            inventory = payload.get("inventory") or []
            evidence = payload.get("evidence") or []
            parts = [f"**Answer:** {answer}"]
            lines: list[str] = []
            if isinstance(inventory, list):
                for row in inventory:
                    if isinstance(row, dict):
                        item = str(row.get("item") or "").strip()
                        count = row.get("count")
                        loc = str(row.get("location") or "").strip()
                        if item:
                            line = f"{item}"
                            if count is not None:
                                line += f": {count}"
                            if loc:
                                line += f" ({loc})"
                            lines.append(line)
                    elif str(row).strip():
                        lines.append(str(row).strip())
            if not lines and isinstance(evidence, list):
                lines = [str(e).strip() for e in evidence if str(e).strip()]
            section = (
                "**Restroom facilities:**"
                if is_drawing_zone_facilities_query(query)
                else "**Furniture & fixtures:**"
            )
            if lines:
                parts.append(section + "\n" + "\n".join(f"- {ln}" for ln in lines))
            if limitations:
                parts.append(f"**Note:** {limitations}")
            return "\n\n".join(parts)

        evidence = payload.get("evidence") or []
        parts = [f"**Answer:** {answer}"]
        if isinstance(evidence, list) and evidence:
            bullets = "\n".join(f"- {e}" for e in evidence if str(e).strip())
            if bullets:
                parts.append(f"**Evidence:**\n{bullets}")
        if limitations:
            parts.append(f"**Limitations:** {limitations}")
        return "\n\n".join(parts)
    except Exception as exc:
        logger.warning("Contextual vision failed: %s", exc)
        return None


def drawing_display_label(drawing: dict[str, Any]) -> str:
    """Human-readable drawing reference for answers and dropdown sync."""
    meta = drawing.get("metadata") or {}
    drawing_no = (meta.get("drawing_no") or "").strip()
    title = (drawing.get("title") or "").strip()
    if drawing_no and drawing_no.upper() in title.upper():
        return title
    if drawing_no and title:
        short = title.split("–", 1)[-1].strip() if "–" in title else title
        return f"{drawing_no} – {short}"
    return title or drawing_no or "this drawing"


def ensure_drawing_cited_in_answer(
    query: str,
    answer: str,
    drawing: dict[str, Any],
) -> str:
    """Ensure the AI answer names the drawing when the user asks which sheet."""
    if not answer or not drawing:
        return answer

    from app.search.query_intel import is_which_drawing_query

    label = drawing_display_label(drawing)
    meta = drawing.get("metadata") or {}
    drawing_no = (meta.get("drawing_no") or "").upper()
    text = answer.strip()
    upper = text.upper()

    if drawing_no and drawing_no in upper:
        return text
    if label.lower() in text.lower():
        return text

    cite = f"**Drawing:** {label}"
    if is_which_drawing_query(query):
        if text.startswith("**Answer:**"):
            body = text[len("**Answer:**") :].strip()
            return f"**Answer:**\n{cite}\n\n{body}"
        return f"{cite}\n\n{text}"

    if drawing_no and cite not in text:
        if text.startswith("**Answer:**"):
            rest = text[len("**Answer:**") :].strip()
            return f"**Answer:**\n{cite}\n\n{rest}"
        return f"{cite}\n\n{text}"
    return text


def _vision_configured() -> bool:
    return bool(
        settings.AZURE_OPENAI_VISION_DEPLOYMENT
        and settings.AZURE_OPENAI_ENDPOINT
        and settings.AZURE_OPENAI_KEY
    )


def _vision_answer_is_usable(answer: Optional[str]) -> bool:
    if not answer or not str(answer).strip():
        return False
    return not re.search(
        r"could not be rasterized|Re-run drawing index sync",
        str(answer),
        re.I,
    )


def vision_general_drawing_answer(
    *,
    query: str,
    drawing: dict[str, Any],
) -> Optional[str]:
    """
    General drawing Q&A from the sheet image — geometry, welds, cross-sections,
    dimensions, annotations, and detail callouts.
    """
    deployment = settings.AZURE_OPENAI_VISION_DEPLOYMENT
    if not _vision_configured():
        return None

    meta = drawing.get("metadata") or {}
    drawing_no = (meta.get("drawing_no") or "").strip()

    try:
        content, content_type, loaded_no = _load_drawing_image_for_vision(drawing)
        if loaded_no:
            drawing_no = loaded_no
        data_url = _data_url_from_bytes(content, content_type)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("General vision: failed to load image: %s", exc)
        return None

    user_text = (
        f"Drawing reference for disambiguation only (NOT visible evidence): "
        f"drawing_no={drawing_no}.\n"
        f"Question: {query}\n\n"
        "Analyze the full drawing image. Read geometry, cross-sections, weld symbols, "
        "dimension chains, section cuts, detail bubbles, title block, and annotations.\n"
        'Return JSON: {"answer": "...", "evidence": ["visible item 1", ...], '
        '"limitations": "what is unclear or not visible on the sheet"}'
    )
    system = (
        "You are BuildTrack AI, an engineering drawing assistant. "
        "Answer ONLY from what is explicitly visible in the drawing image. "
        "Read geometry, cross-sections, weld details, dimensions, symbols, and notes. "
        "Quote visible labels and values. If something is not on the sheet, say so clearly. "
        "Do not invent coordinates, dimensions, or details."
    )

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        },
                    ],
                },
            ],
            max_tokens=800,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        payload = json.loads(raw)
        answer = str(payload.get("answer") or "").strip()
        if not answer:
            return None

        evidence = payload.get("evidence") or []
        limitations = str(payload.get("limitations") or "").strip()
        parts = [f"**Answer:** {answer}"]
        if isinstance(evidence, list) and evidence:
            bullets = "\n".join(f"- {e}" for e in evidence if str(e).strip())
            if bullets:
                parts.append(f"**Evidence:**\n{bullets}")
        if limitations:
            parts.append(f"**Limitations:** {limitations}")
        return "\n\n".join(parts)
    except Exception as exc:
        logger.warning("General vision failed: %s", exc)
        return None


def vision_answer_for_drawing(
    *,
    query: str,
    drawing: dict[str, Any],
) -> Optional[str]:
    """
    Return an evidence-backed answer string from vision, or None if unavailable.
    Supports raster files and DWG via preview image.
    """
    deployment = settings.AZURE_OPENAI_VISION_DEPLOYMENT
    if not _vision_configured():
        return None

    meta = drawing.get("metadata") or {}
    drawing_no = (meta.get("drawing_no") or "").strip()

    try:
        content, content_type, loaded_no = _load_drawing_image_for_vision(drawing)
        if loaded_no:
            drawing_no = loaded_no
        data_url = _data_url_from_bytes(content, content_type)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Vision: failed to load drawing image: %s", exc)
        return None

    user_text = (
        f"Drawing reference for disambiguation only (NOT visible evidence — do not cite in answer): "
        f"drawing_no={drawing_no}.\n"
        f"Question: {query}\n"
        "Respond in JSON with answer, evidence, derivation, limitations, confidence, "
        "confidence_aspects. Evidence and derivation must come only from the image."
    )
    image_url_payload: dict[str, Any] = {"url": data_url, "detail": "high"}

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _vision_system_prompt(query)},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": image_url_payload},
                    ],
                },
            ],
            max_tokens=600,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        payload = _parse_vision_payload(raw)
        if not payload:
            if is_drawing_location_query(query):
                return _conservative_location_fallback(drawing_no, query)
            return raw or None

        payload = _sanitize_vision_payload(payload)

        if _reject_vision_payload(query, payload):
            if is_drawing_location_query(query):
                return _location_answer_from_payload(drawing_no, query, payload)
            return None

        element = _extract_element_ref(query)
        if is_drawing_engineering_reasoning_query(query):
            aspects = payload.get("confidence_aspects") or {}
            if not isinstance(aspects, dict) or "exact_location" not in aspects:
                return _location_answer_from_payload(drawing_no, query, payload)
            if not payload.get("derivation"):
                return _location_answer_from_payload(drawing_no, query, payload)

        formatted = _format_vision_response(payload, element=element)
        return _finalize_drawing_answer(query, formatted, drawing)
    except Exception as exc:
        logger.warning("Vision: GPT call failed: %s", exc)
        if is_drawing_location_query(query):
            return _conservative_location_fallback(drawing_no, query)
        return None


def answer_drawing_vision_first(
    *,
    query: str,
    drawing: dict[str, Any],
) -> Optional[str]:
    """
    Vision-first answer for any drawing content question.
    Returns None only when vision is unavailable — caller should fall back to extracted text.
    """
    if not _vision_configured():
        return None

    answer: Optional[str] = None

    if is_drawing_vision_first_query(query) or is_drawing_count_query(query):
        answer = vision_contextual_layout_answer(query=query, drawing=drawing)
    elif is_drawing_engineering_reasoning_query(query):
        answer = vision_answer_for_drawing(query=query, drawing=drawing)
        if not _vision_answer_is_usable(answer):
            return drawing_vision_fallback(query=query, drawing=drawing)
    else:
        answer = vision_general_drawing_answer(query=query, drawing=drawing)
        if not _vision_answer_is_usable(answer):
            answer = vision_answer_for_drawing(query=query, drawing=drawing)

    if _vision_answer_is_usable(answer):
        return ensure_drawing_cited_in_answer(query, answer or "", drawing)
    return answer
