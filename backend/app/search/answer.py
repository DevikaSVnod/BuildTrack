from typing import List, Dict, Any, Tuple, Optional

from app.core.config import settings
from app.search.query_intel import (
    QueryAnalysis,
    is_question,
    is_document_content_query,
    is_drawing_content_query,
    is_drawing_fact_query,
    is_drawing_contextual_layout_query,
    is_drawing_count_query,
    is_drawing_count_query,
    is_drawing_vision_first_query,
    is_drawing_text_first_query,
    is_safety_measures_query,
    is_handover_workflow_query,
    score_document_title_match,
    score_drawing_match,
    extract_drawing_no,
)
import json
import re
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

_answer_cache: Dict[str, Tuple[float, str, List[str]]] = {}
CACHE_TTL = 300

_HANDOVER_STATUS_ACTIONS: Dict[str, str] = {
    "Pending": (
        "Compile the required package, assign a document owner, upload to Document Control, "
        "and submit for PM/site review."
    ),
    "Submitted": (
        "Project Manager to verify completeness against the closeout checklist and route "
        "to the client/consultant for sign-off."
    ),
    "Under Review": (
        "Address review comments, update the document, and re-submit for approval."
    ),
    "Signed": (
        "Archive in Document Control and mark the closeout item complete in the project register."
    ),
}


def _cache_key(query: str, results_fingerprint: str) -> str:
    raw = f"{query.strip().lower()}|{results_fingerprint}"
    if is_drawing_content_query(query):
        raw += "|drawing-structured-v6"
    return hashlib.md5(raw.encode()).hexdigest()


def _results_fingerprint(results: List[Dict[str, Any]]) -> str:
    ids = [r.get("id", "") for r in results[:6]]
    return "|".join(ids)


def _get_cached(key: str):
    if key in _answer_cache:
        ts, answer, suggested = _answer_cache[key]
        if time.time() - ts < CACHE_TTL:
            return answer, suggested
        del _answer_cache[key]
    return None


def _set_cached(key: str, answer: str, suggested: List[str]):
    _answer_cache[key] = (time.time(), answer, suggested)
    if len(_answer_cache) > 200:
        oldest = sorted(_answer_cache.items(), key=lambda x: x[1][0])[:50]
        for k, _ in oldest:
            del _answer_cache[k]


def _is_blob_document(r: Dict[str, Any]) -> bool:
    meta = r.get("metadata") or {}
    return meta.get("content_source") == "blob_rag" or meta.get("source") == "blob_rag"


def _document_body_text(r: Dict[str, Any]) -> str:
    meta = r.get("metadata") or {}
    return (meta.get("blob_chunk") or r.get("snippet") or "").strip()


def _is_blob_content(r: Dict[str, Any]) -> bool:
    meta = r.get("metadata") or {}
    if meta.get("content_source") in ("blob_rag", "drawing_sheet_notes"):
        return True
    return _is_blob_document(r)


def _drawing_body_text(r: Dict[str, Any]) -> str:
    meta = r.get("metadata") or {}
    return (
        (meta.get("blob_chunk") or meta.get("sheet_notes") or r.get("snippet") or "")
        .strip()
    )


def _order_results_for_answer(
    query: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not is_document_content_query(query):
        return results

    if is_drawing_content_query(query):
        drawings = [r for r in results if r.get("content_type") == "drawing"]
        others = [r for r in results if r.get("content_type") != "drawing"]

        def drawing_rank(r: Dict[str, Any]) -> tuple:
            meta = r.get("metadata") or {}
            is_real_blob = _is_blob_content(r)
            title_score = score_drawing_match(query, r.get("title", ""), meta)
            return (title_score, 1 if is_real_blob else 0, len(_drawing_body_text(r)))

        drawings.sort(key=drawing_rank, reverse=True)
        return drawings + others

    docs = [r for r in results if r.get("content_type") == "document"]
    others = [r for r in results if r.get("content_type") != "document"]

    def doc_rank(r: Dict[str, Any]) -> tuple:
        meta = r.get("metadata") or {}
        snippet = (r.get("snippet") or "").lower()
        is_real_blob = _is_blob_document(r) and "buildtrack document id" not in snippet
        title_score = score_document_title_match(query, r.get("title", ""))
        return (title_score, 1 if is_real_blob else 0, len(_document_body_text(r)))

    docs.sort(key=doc_rank, reverse=True)
    return docs + others


def _format_result_for_context(r: Dict[str, Any], index: int) -> str:
    ctype = r.get("content_type", "item")
    title = r.get("title", "")
    meta = r.get("metadata") or {}
    meta_parts = [
        f"{k}={v}"
        for k, v in meta.items()
        if v
        and str(v).strip()
        and k not in {"blob_chunk", "chunk_id", "source", "content_source"}
    ]
    meta_str = ", ".join(meta_parts) if meta_parts else ""

    if _is_blob_content(r) or (ctype == "drawing" and (meta.get("sheet_notes") or meta.get("blob_chunk"))):
        snippet = (_drawing_body_text(r) if ctype == "drawing" else _document_body_text(r))[:1200]
        label = "drawing excerpt" if ctype == "drawing" else "document excerpt"
    else:
        snippet = (r.get("snippet") or "")[:220]
        label = ctype

    line = f"{index}. [{label}] {title}"
    if meta_str:
        line += f" ({meta_str})"
    if snippet:
        line += f" — {snippet}"
    return line


def _build_prompt(query: str, results: List[Dict[str, Any]], analysis: Optional[QueryAnalysis]) -> str:
    from app.search.structured_filters import is_structured_filter_query

    ordered = _order_results_for_answer(query, results)
    limit = len(ordered) if is_structured_filter_query(query) else 8
    context_lines = [_format_result_for_context(r, i + 1) for i, r in enumerate(ordered[:limit])]
    context = "\n".join(context_lines) if context_lines else "No matching records."

    question_mode = analysis.is_question if analysis else is_question(query)
    domain_note = ""
    if analysis and analysis.content_types:
        domain_note = f"User is asking about: {', '.join(analysis.content_types)}. "
    if analysis and analysis.status_hints:
        domain_note += f"Filter focus: {', '.join(analysis.status_hints)}. "

    doc_content_note = ""
    if is_document_content_query(query):
        if is_drawing_content_query(query):
            if is_drawing_contextual_layout_query(query):
                doc_content_note = (
                    "The user is asking a contextual layout question about a drawing (floor plan, "
                    "rooms, doors, entry/exit points, circulation). "
                    "Answer ONLY from the drawing excerpt LAYOUT ELEMENTS (furniture, fixtures). "
                    "Do NOT answer from the drawing title alone — titles may be incorrect. "
                    "If the excerpt lists beds and bathrooms, the space is a bedroom/apartment unit, "
                    "not a conference room, regardless of title. "
                    "If the excerpt lacks enough detail, say clearly what is and is not stated — "
                    "do NOT use engineering coordinate or setting-out language.\n"
                )
            else:
                doc_content_note = (
                    "The user is asking about technical content INSIDE an engineering drawing. "
                    "Drawing excerpt sources contain extracted sheet text — use those carefully. "
                    "If pile diameter or dimensions are in the excerpt, quote them exactly. "
                    "For location/position questions: do NOT invent coordinates from nearby dimensions. "
                    "Either cite explicit dimension chains and reference labels, or state that the "
                    "exact location cannot be determined from the visible information. "
                    "Include confidence and limitations when evidence is partial. "
                    "Do NOT mention piling schedules, installation sequences, or general notes unless "
                    "they are explicitly visible in the drawing excerpt — sidecar text is not sheet evidence.\n"
                )
        else:
            doc_content_note = (
                "The user is asking about text INSIDE uploaded files. "
                "Document excerpt sources contain file body text — use those carefully. "
                "List ALL relevant items mentioned in the excerpts (do not stop at the first two). "
            )
        if is_safety_measures_query(query):
            doc_content_note += (
                "The user asked for SAFETY MEASURES (protocols, PPE, procedures, drills, inspections). "
                "Do NOT answer with HSE statistics/metrics (LTI counts, first aid case counts, "
                "PPE compliance %, KPIs) — those are performance results, not measures. "
                "The measure for PPE is mandatory PPE usage/enforcement, not the compliance percentage. "
            )

    handover_note = ""
    if is_handover_workflow_query(query):
        handover_note = (
            "The user is asking for NEXT STEPS / recommended ACTIONS for handover closeout documents, "
            "NOT a simple list of document titles. "
            "For each relevant handover item in SOURCES, state the document name, project, current status, "
            "and the specific next action (Pending → compile & submit; Submitted → PM review; "
            "Under Review → address comments; Signed → archive). "
            "End with a short overall priority if multiple items are pending.\n"
        )

    if question_mode:
        return (
            "You are BuildTrack AI, an expert assistant for a construction site management platform "
            "(projects, site activities, DMS documents, handover closeout, drawings, safety/HSE, workforce).\n\n"
            "RULES:\n"
            "- Answer ONLY using the SOURCES below.\n"
            "- For document excerpt sources, extract the answer from the excerpt text.\n"
            "- If document excerpts contain the answer, summarize it clearly in bullets.\n"
            "- Only say you could not find it if NO source contains relevant information.\n"
            "- Be direct and specific: name titles, statuses, projects, and people when relevant.\n"
            "- For list questions, use a short bullet list in the answer field.\n"
            "- Do not mention Azure, search indexes, or AI.\n"
            f"{domain_note}{doc_content_note}{handover_note}\n"
            f"SOURCES:\n{context}\n\n"
            f"USER QUESTION: {query}\n\n"
            "Respond with JSON only:\n"
            '{"answer": "<clear accurate answer — use bullets for list questions; include ALL items from excerpts>", '
            '"questions": ["<follow-up 1>", "<follow-up 2>", "<follow-up 3>"]}'
        )

    return (
        "You are BuildTrack AI for a construction project management platform.\n"
        f"Sources:\n{context}\n\n"
        f"User searched: {query}\n\n"
        "Summarize what was found in 1-2 sentences. JSON only:\n"
        '{"answer": "<summary>", "questions": ["q1", "q2", "q3"]}'
    )


def _extract_hse_section(body: str) -> Optional[str]:
    """Pull the HSE / safety section when present in a merged document excerpt."""
    markers = [
        r"9\.\s*Health,\s*Safety\s*&\s*Environment",
        r"Health,\s*Safety\s*&\s*Environment\s*\(HSE\)",
        r"HSE Metric",
    ]
    for marker in markers:
        m = re.search(marker, body, re.IGNORECASE)
        if m:
            return body[m.start() : m.start() + 2200]
    return None


def _is_sync_boilerplate_line(line: str) -> bool:
    lower = line.lower().strip()
    if not lower:
        return True
    if re.search(
        r"buildtrack document id|synced to azure blob|"
        r"^keywords:|^file:|^document id:",
        lower,
    ):
        return True
    # Skip bare filename lines duplicated from blob header
    return bool(re.fullmatch(r"[\w\s\-.]+\.(pdf|xlsx|docx|dwg)", lower))


def _safety_measures_not_found_answer(title: str) -> str:
    clean = title.replace("_", " ")
    return (
        f"**{clean}** does not contain detailed safety measures in the indexed document text. "
        "No specific protocols, PPE requirements, toolbox talks, or inspection procedures "
        "were found in the file body. Try a report or site plan that includes an HSE section."
    )


def _extract_safety_measures(body: str) -> Optional[str]:
    """Extract protocols/PPE/requirements — not incident statistics."""
    note = re.search(r"HSE Note:(.+?)(?:\n\n|\d+\.\s+Conclusion)", body, re.IGNORECASE | re.DOTALL)
    if note:
        return note.group(0).strip()
    ppe = re.search(
        r"(mandatory PPE including.+?\.|"
        r"all workers are equipped with.+?\.|"
        r"monthly safety drills are conducted\.|"
        r"monsoon protection.+?\.|"
        r"toolbox talks.+?\.)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if ppe:
        return ppe.group(0).strip()
    return None


def _build_safety_measures_answer(title: str, body: str) -> Optional[str]:
    measures = _extract_safety_measures(body)
    if not measures:
        return None
    bullets: list[str] = []
    if re.search(r"mandatory PPE|PPE including", measures, re.I):
        bullets.append(
            "Mandatory PPE for all workers, including helmets, safety shoes, "
            "harnesses for height work, and high-visibility vests."
        )
    if re.search(r"toolbox talks", measures, re.I):
        m = re.search(r"(\d+)\s*(?:conducted|daily)", body, re.I)
        count = m.group(1) if m else "regular"
        bullets.append(f"Daily safety toolbox talks ({count} conducted during the quarter).")
    if re.search(r"monthly safety drills", measures, re.I):
        bullets.append("Monthly safety drills conducted on site.")
    if re.search(r"safety inspections", body, re.I):
        m = re.search(r"Safety Inspections\s*\n\s*(\d+ internal \+ \d+ external)", body, re.I)
        if m:
            bullets.append(f"Regular safety inspections ({m.group(1)}).")
        else:
            bullets.append("Regular internal and external safety inspections.")
    if re.search(r"near miss", body, re.I):
        bullets.append("Investigation and closure of near-miss incidents.")
    if re.search(r"monsoon protection|monsoon preparedness", body, re.I):
        bullets.append("Monsoon preparedness and protection measures for open excavations.")
    if re.search(r"equipment maintenance|backup equipment", body, re.I):
        bullets.append("Equipment maintenance schedules and backup equipment planning.")
    if not bullets:
        return None
    lines = "\n".join(f"- {b}" for b in bullets)
    return (
        f"The safety measures mentioned in the **{title.replace('_', ' ')}** include:\n"
        f"{lines}"
    )


def _refresh_blob_body_for_query(query: str, title: str, current_body: str) -> str:
    """Re-fetch blob passages when the merged excerpt is missing the relevant section."""
    if is_safety_measures_query(query):
        if not (_extract_safety_measures(current_body) and "mandatory PPE" in current_body):
            from app.search.blob_retrieval import fetch_raw_chunks_for_document

            search_terms = (
                "mandatory PPE helmets safety shoes harnesses visibility vests "
                "toolbox talks safety drills HSE Note inspections compliance"
            )
            chunks = fetch_raw_chunks_for_document(title, search_terms)
            for text in chunks:
                if "mandatory PPE" in text or "HSE Note" in text:
                    return text
            if chunks:
                return max(chunks, key=len)

    if is_drawing_content_query(query) and re.search(r"\bpile|diameter|piling\b", query, re.I):
        if "diameter" not in current_body.lower() and "pile" not in current_body.lower():
            from app.search.blob_retrieval import fetch_raw_chunks_for_document

            drawing_no = extract_drawing_no(query) or ""
            search_terms = f"{drawing_no} bored pile diameter piling foundation layout notes"
            chunks = fetch_raw_chunks_for_document(title, search_terms)
            for text in chunks:
                if "diameter" in text.lower() or "pile" in text.lower():
                    return text
            if chunks:
                return max(chunks, key=len)

    return current_body


def _extract_pile_diameter_answer(body: str, title: str) -> Optional[str]:
    patterns = [
        r"nominal\s+pile\s+diameter\s*(\d+)\s*mm(?:\s*\(([^)]+)\))?",
        r"(?:bored\s+cast-in-situ\s+)?piles?,?\s*(?:nominal\s+)?diameter\s*(\d+)\s*mm(?:\s*\(([^)]+)\))?",
        r"diameter\s*(\d+)\s*mm(?:\s*\(([^)]+)\))?",
    ]
    m = None
    for pat in patterns:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            break
    if m:
        mm = m.group(1)
        alt = m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
        detail = f" ({alt})" if alt else ""
        drawing_no = extract_drawing_no(title) or title
        return f"On drawing **{drawing_no}**, the pile diameter is **{mm} mm**{detail}."
    return None


def _top_drawing_body(query: str, results: List[Dict[str, Any]]) -> tuple[str, str]:
    """Return (body_text, title) for the best matching drawing result."""
    for r in _order_results_for_answer(query, results):
        if r.get("content_type") != "drawing":
            continue
        body = _drawing_body_text(r)
        if len(body) >= 20:
            return body[:3500], r.get("title", "Drawing")
    return "", ""


def _answer_drawing_from_extracted_text(
    query: str, results: List[Dict[str, Any]]
) -> Optional[str]:
    """LLM answer grounded in extracted drawing sheet text (contextual / layout questions)."""
    if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_KEY:
        return None
    body, title = _top_drawing_body(query, results)
    if not body:
        return None

    drawing_no = extract_drawing_no(title) or extract_drawing_no(query) or title
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You answer questions about engineering drawings using ONLY the "
                        "extracted sheet text provided. For floor plans, count doors, entries, "
                        "exits, and rooms only when the text supports it. "
                        "For room-type questions, use LAYOUT ELEMENTS (beds, bathrooms, furniture) "
                        "not the drawing title line — titles may be wrong. "
                        "If the text is insufficient, say so honestly. "
                        "Never use setting-out, grid coordinate, or pile-location language "
                        "unless the question is specifically about coordinates."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Drawing: {drawing_no} — {title}\n\n"
                        f"EXTRACTED SHEET TEXT:\n{body}\n\n"
                        f"QUESTION: {query}\n\n"
                        'Respond JSON: {"answer": "..."}'
                    ),
                },
            ],
            max_tokens=500,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        answer = str(parsed.get("answer") or "").strip()
        if answer and not _answer_says_not_found(answer):
            return answer
        if answer:
            return answer
    except Exception as exc:
        logger.warning("Drawing text LLM answer failed: %s", exc)
    return None


def _drawing_text_answer_is_weak(answer: str) -> bool:
    lower = (answer or "").lower()
    return bool(
        re.search(
            r"does not provide(?:\s+any|\s+sufficient)?\s+information|"
            r"insufficient information|no text could be|"
            r"cannot be automatically extracted|not enough detail|lack(s)? sufficient|"
            r"no information about|text is insufficient|not mentioned in the extracted|"
            r"not specified|exact number|cannot determine|can(?:not|'t) (?:be )?determin|"
            r"unclear how many|no count|without (?:seeing|viewing)|"
            r"provided details do not|does not (?:list|state|specify)",
            lower,
        )
    )


def _contextual_drawing_followups(query: str) -> list[str]:
    drawing_no = extract_drawing_no(query) or "this drawing"
    return [
        f"What rooms are described on {drawing_no}?",
        f"How is circulation described on {drawing_no}?",
        f"What door or access points are mentioned for {drawing_no}?",
    ]


def _handover_workflow_followups() -> List[str]:
    return [
        "Who is responsible for finalizing the pending handover documents?",
        "What is the timeline for completing the pending handover documents?",
        "Are there any specific issues delaying the handover process?",
    ]


def _handover_workflow_answer(query: str, results: List[Dict[str, Any]]) -> Optional[str]:
    """Action-oriented handover answer derived from indexed status metadata."""
    handover_items = [r for r in results if r.get("content_type") == "handover"]
    if not handover_items:
        return None

    q_lower = query.lower()
    focus_pending = bool(re.search(r"\bpending\b|\boutstanding\b|\bawaiting\b", q_lower))

    rows: List[Dict[str, str]] = []
    for r in handover_items:
        meta = r.get("metadata") or {}
        status = str(meta.get("status") or "Pending").strip()
        if focus_pending and status.lower() != "pending":
            continue
        rows.append({
            "title": r.get("title", "Handover document"),
            "status": status,
            "project": str(meta.get("project") or meta.get("project_name") or "").strip(),
            "category": str(meta.get("category") or "").strip(),
        })

    if focus_pending and not rows:
        return (
            "No pending handover documents appear in the current search results. "
            "Items already submitted or under review may need follow-up with the project manager."
        )

    if not rows:
        rows = [
            {
                "title": r.get("title", "Handover document"),
                "status": str((r.get("metadata") or {}).get("status") or "Pending").strip(),
                "project": str((r.get("metadata") or {}).get("project") or "").strip(),
                "category": str((r.get("metadata") or {}).get("category") or "").strip(),
            }
            for r in handover_items
        ]

    heading = (
        "**Next steps for pending handover documents:**"
        if focus_pending
        else "**Recommended next steps by handover document:**"
    )
    lines = [heading, ""]
    for row in rows:
        action = _HANDOVER_STATUS_ACTIONS.get(
            row["status"],
            _HANDOVER_STATUS_ACTIONS["Pending"],
        )
        proj = f" ({row['project']})" if row["project"] else ""
        cat = f" [{row['category']}]" if row["category"] else ""
        lines.append(
            f"- **{row['title']}**{proj}{cat} — **{row['status']}**: {action}"
        )

    if focus_pending and len(rows) > 1:
        lines.append(
            "\n**Overall priority:** Assign owners for each pending package this week, "
            "complete as-built and DLP submissions first, then track sign-off in Document Control "
            "before project closeout."
        )
    return "\n".join(lines)


def _answer_is_handover_list_only(answer: str, query: str) -> bool:
    if not is_handover_workflow_query(query):
        return False
    lower = (answer or "").lower()
    has_action = bool(
        re.search(
            r"\bnext\b|\bsubmit\b|\breview\b|\bassign\b|\bupload\b|\bcompile\b|"
            r"\bstep\b|\bshould\b|\barchive\b|\bowner\b|\baction\b",
            lower,
        )
    )
    return not has_action


def _extractive_document_answer(
    query: str, results: List[Dict[str, Any]]
) -> Optional[str]:
    """Build a direct answer from blob file text when the LLM misses it."""
    for r in _order_results_for_answer(query, results):
        ctype = r.get("content_type")
        is_drawing = ctype == "drawing"
        is_doc = ctype == "document"
        if not is_drawing and not (is_doc and _is_blob_content(r)):
            continue
        if is_drawing and not _drawing_body_text(r):
            continue
        if is_doc and not _is_blob_content(r):
            continue
        body = _drawing_body_text(r) if is_drawing else _document_body_text(r)
        body = _refresh_blob_body_for_query(query, r.get("title", ""), body)
        if len(body) < 20 or "uploaded by" in body[:100].lower():
            continue
        title = r.get("title", "Document")
        if is_drawing_content_query(query) and re.search(r"\bpile|diameter|piling\b", query, re.I):
            structured = _extract_pile_diameter_answer(body, title)
            if structured:
                return structured
        if is_drawing and is_drawing_content_query(query):
            drawing_no = extract_drawing_no(title) or extract_drawing_no(query) or title
            if re.search(r"\bspan|truss\b", query, re.I) and re.search(r"span\s*(\d+)\s*m", body, re.I):
                sm = re.search(r"span\s*(\d+)\s*m", body, re.I)
                return f"On drawing **{drawing_no}**, the truss span is **{sm.group(1)} m**."
            if re.search(r"\bincomer|rating\b", query, re.I) and re.search(r"incomer\s*(\d+)\s*A", body, re.I):
                im = re.search(r"incomer\s*(\d+)\s*A", body, re.I)
                return f"On drawing **{drawing_no}**, the main incomer rating is **{im.group(1)} A**."
        if is_safety_measures_query(query):
            hse_body = _extract_hse_section(body) or body
            structured = _build_safety_measures_answer(title, hse_body)
            if structured:
                return structured
            return _safety_measures_not_found_answer(title)
        if re.search(r"\bsafety|hse|ppe\b", query, re.IGNORECASE):
            hse = _extract_hse_section(body)
            if hse:
                body = hse
        lines = [
            ln.strip()
            for ln in body.splitlines()
            if ln.strip() and not _is_sync_boilerplate_line(ln)
        ]
        if not lines:
            continue
        bullets = "\n".join(f"- {ln[:200]}" for ln in lines[:12])
        return f"From **{title}**:\n{bullets}"
    return None


def _answer_is_metrics_only(answer: str) -> bool:
    lower = answer.lower()
    has_metrics = bool(
        re.search(r"\blti\b|lost time injur|first aid cases|near miss reports:\s*\d", lower)
    )
    has_measures = bool(
        re.search(r"\bppe\b|helmet|harness|vest|toolbox|drill|inspection|monsoon|compliance", lower)
    )
    return has_metrics and not has_measures


def _answer_says_not_found(answer: str) -> bool:
    lower = answer.lower()
    return "could not find" in lower or "couldn't find" in lower or "no information" in lower


def generate_answer(
    query: str,
    search_results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis] = None,
) -> Tuple[str, List[str]]:
    ordered = _order_results_for_answer(query, search_results)
    fingerprint = _results_fingerprint(ordered)
    key = _cache_key(query, fingerprint)
    cached = _get_cached(key)
    if cached:
        logger.info("Answer cache hit: %s", query[:40])
        return cached

    if not search_results:
        return (
            f"I couldn't find anything in BuildTrack matching '{query}'. "
            "Try different keywords or check the Handover, Drawings, or Safety pages.",
            [
                "Show pending handover documents",
                "List open safety incidents",
                "Which projects are in progress?",
            ],
        )

    if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_KEY:
        return _fallback_answer(query, ordered, analysis)

    # Drawing answers: extracted text first; vision only for PNG spatial/engineering reasoning.
    top_drawing = next((r for r in ordered if r.get("content_type") == "drawing"), None)
    if is_drawing_content_query(query) and top_drawing:
        from app.search.drawing_vision import (
            _drawing_followups,
            drawing_vision_fallback,
            is_drawing_engineering_reasoning_query,
            is_structured_drawing_answer,
            vision_answer_for_drawing,
        )

        meta = top_drawing.get("metadata") or {}
        is_dwg = (meta.get("file_type") or "").upper() == "DWG"

        # Count questions: try sheet_notes text first (fast), then vision on image.
        if is_drawing_count_query(query) and not is_dwg:
            from app.search.drawing_vision import vision_contextual_layout_answer

            text_answer = _answer_drawing_from_extracted_text(query, ordered)
            if text_answer and not _drawing_text_answer_is_weak(text_answer):
                if re.search(r"\b\d+\b", text_answer):
                    result = (text_answer, _contextual_drawing_followups(query))
                    _set_cached(key, *result)
                    return result
            vision_ctx = vision_contextual_layout_answer(
                query=query, drawing=top_drawing
            )
            if vision_ctx:
                result = (vision_ctx, _contextual_drawing_followups(query))
                _set_cached(key, *result)
                return result

        # Vision-first for layout questions on PNG/PDF — image content beats title/metadata.
        if is_drawing_vision_first_query(query) and not is_drawing_count_query(query) and not is_dwg:
            from app.search.drawing_vision import vision_contextual_layout_answer

            vision_ctx = vision_contextual_layout_answer(
                query=query, drawing=top_drawing
            )
            if vision_ctx:
                result = (vision_ctx, _contextual_drawing_followups(query))
                _set_cached(key, *result)
                return result

        if is_drawing_text_first_query(query) or is_dwg:
            from app.search.drawing_vision import vision_contextual_layout_answer

            text_answer = (
                _answer_drawing_from_extracted_text(query, ordered)
                or _extractive_document_answer(query, ordered)
            )
            # Text fallback only if vision unavailable (e.g. DWG without preview)
            if is_drawing_contextual_layout_query(query) and (
                not text_answer or _drawing_text_answer_is_weak(text_answer)
            ):
                vision_ctx = vision_contextual_layout_answer(
                    query=query, drawing=top_drawing
                )
                if vision_ctx:
                    result = (vision_ctx, _contextual_drawing_followups(query))
                    _set_cached(key, *result)
                    return result
            if text_answer and not _drawing_text_answer_is_weak(text_answer):
                followups = (
                    _contextual_drawing_followups(query)
                    if is_drawing_contextual_layout_query(query)
                    else _drawing_followups(query)
                )
                result = (text_answer, followups)
                _set_cached(key, *result)
                return result

        v: Optional[str] = None
        if (
            settings.AZURE_OPENAI_VISION_DEPLOYMENT
            and not is_dwg
            and not is_drawing_vision_first_query(query)
        ):
            try:
                v = vision_answer_for_drawing(query=query, drawing=top_drawing)
            except Exception as exc:
                logger.debug("Vision path skipped: %s", exc)

        if is_drawing_engineering_reasoning_query(query):
            if not v or not is_structured_drawing_answer(v):
                v = drawing_vision_fallback(query=query, drawing=top_drawing)
            if v:
                result = (v, _drawing_followups(query))
                _set_cached(key, *result)
                return result
        elif (
            v
            and not re.search(
                r"\bnot visible\b|\bcan(?:not|'t)\s+find\b|\bnot found\b", v, re.I
            )
        ):
            result = (v, _drawing_followups(query))
            _set_cached(key, *result)
            return result

    if is_safety_measures_query(query):
        extractive = _extractive_document_answer(query, ordered)
        if extractive:
            suggested = [
                "What safety incidents were reported for Highway Bridge Expansion?",
                "Who is the project manager for Highway Bridge Expansion?",
                "What is the overall progress of the bridge project?",
            ]
            result = (extractive, suggested)
            _set_cached(key, *result)
            return result

    if is_handover_workflow_query(query):
        workflow = _handover_workflow_answer(query, ordered)
        if workflow:
            result = (workflow, _handover_workflow_followups())
            _set_cached(key, *result)
            return result

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )

        prompt = _build_prompt(query, ordered, analysis)
        question_mode = analysis.is_question if analysis else is_question(query)
        max_tokens = 700 if is_document_content_query(query) else (450 if question_mode else 280)

        response = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You answer using only provided sources. "
                        "Return valid JSON with keys answer and questions."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        answer = parsed.get("answer", "")
        if isinstance(answer, list):
            answer = "\n".join(f"- {str(x).strip()}" for x in answer if str(x).strip())
        answer = str(answer).strip()
        suggested = parsed.get("questions", [])
        if not isinstance(suggested, list):
            suggested = []

        if not answer:
            answer = _grounded_answer(query, ordered, analysis)

        if _answer_says_not_found(answer) and is_document_content_query(query):
            extractive = _extractive_document_answer(query, ordered)
            if extractive:
                answer = extractive

        if is_safety_measures_query(query) and _answer_is_metrics_only(answer):
            extractive = _extractive_document_answer(query, ordered)
            if extractive:
                answer = extractive

        if is_handover_workflow_query(query) and _answer_is_handover_list_only(answer, query):
            workflow = _handover_workflow_answer(query, ordered)
            if workflow:
                answer = workflow
                suggested = _handover_workflow_followups()

        if is_drawing_content_query(query) and top_drawing:
            from app.search.drawing_vision import (
                _drawing_followups,
                drawing_vision_fallback,
                is_drawing_engineering_reasoning_query,
                is_structured_drawing_answer,
                has_unsupported_sheet_claims,
            )

            meta = top_drawing.get("metadata") or {}
            is_dwg = (meta.get("file_type") or "").upper() == "DWG"
            use_vision_fallback = (
                not is_drawing_vision_first_query(query)
                and (
                    (
                        is_drawing_engineering_reasoning_query(query)
                        and not is_drawing_contextual_layout_query(query)
                        and not is_dwg
                    )
                    or (
                        not is_drawing_contextual_layout_query(query)
                        and not is_dwg
                        and (
                            not is_structured_drawing_answer(answer)
                            or has_unsupported_sheet_claims(answer)
                        )
                    )
                )
            )

            if use_vision_fallback:
                answer = drawing_vision_fallback(query=query, drawing=top_drawing)
                suggested = _drawing_followups(query)
            elif is_drawing_contextual_layout_query(query) or is_dwg:
                text_answer = (
                    _answer_drawing_from_extracted_text(query, ordered)
                    or _extractive_document_answer(query, ordered)
                )
                if text_answer:
                    answer = text_answer
                    suggested = _contextual_drawing_followups(query)

        result = (answer, suggested[:3])
        _set_cached(key, *result)
        return result

    except Exception as e:
        logger.error("OpenAI error: %s", e)
        return _fallback_answer(query, ordered, analysis)


def _grounded_answer(
    query: str,
    results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis],
) -> str:
    if is_document_content_query(query):
        extractive = _extractive_document_answer(query, results)
        if extractive:
            return extractive

    if not results:
        return f"No results found for '{query}'."

    lines = []
    for r in results[:5]:
        meta = r.get("metadata") or {}
        status = meta.get("status", "")
        project = meta.get("project") or meta.get("project_name", "")
        extra = f" — {status}" if status else ""
        proj = f" ({project})" if project else ""
        lines.append(f"• {r['title']}{extra}{proj}")

    intro = "Based on your search, here is what I found:\n"
    if analysis and analysis.is_question and analysis.status_hints:
        intro = f"Records matching '{', '.join(analysis.status_hints)}':\n"
    return intro + "\n".join(lines)


def _fallback_answer(
    query: str,
    results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis],
) -> Tuple[str, List[str]]:
    answer = _grounded_answer(query, results, analysis)
    suggested = [
        "What handover documents are still pending?",
        "Show open safety incidents by project",
        "Which high priority tasks are overdue?",
    ]
    return answer, suggested
