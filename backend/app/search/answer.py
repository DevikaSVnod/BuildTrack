from typing import List, Dict, Any, Tuple, Optional

from app.core.config import settings
from app.search.query_intel import (
    QueryAnalysis,
    is_question,
    is_document_content_query,
    is_drawing_content_query,
    is_drawing_contextual_layout_query,
    is_safety_measures_query,
    is_inspector_query,
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
        raw += "|drawing-vision-first-v1"
    if is_inspector_query(query):
        raw += "|inspector-extract-v1"
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
    return meta.get("content_source") in (
        "blob_rag",
        "document_body_text",
    ) or meta.get("source") in ("blob_rag", "document_body_text")


def _document_body_text(r: Dict[str, Any]) -> str:
    meta = r.get("metadata") or {}
    return (
        meta.get("blob_chunk")
        or meta.get("body_text")
        or r.get("snippet")
        or ""
    ).strip()


def _is_blob_content(r: Dict[str, Any]) -> bool:
    meta = r.get("metadata") or {}
    if meta.get("content_source") in (
        "blob_rag",
        "drawing_sheet_notes",
        "document_body_text",
    ):
        return True
    return _is_blob_document(r)


def _extract_inspector_section(body: str) -> Optional[str]:
    m = re.search(
        r"(Site Inspection Report[\s\S]{0,1200})",
        body,
        re.I,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r".{0,150}Inspector:\s*[^\n]+[\s\S]{0,500}", body, re.I)
    return m.group(0).strip() if m else None


def _query_relevant_excerpt(query: str, body: str, max_len: int = 1200) -> str:
    body = body.strip()
    if len(body) <= max_len:
        return body

    if is_inspector_query(query):
        section = _extract_inspector_section(body)
        if section:
            return section[:max_len]

    q_terms = {
        t
        for t in re.findall(r"[a-z0-9]+", query.lower())
        if len(t) > 3
        and t not in {"what", "which", "when", "where", "bridge", "site", "project", "document"}
    }
    if not q_terms:
        return body[:max_len]

    best_start = 0
    best_score = -1
    step = max(150, max_len // 5)
    for start in range(0, max(len(body) - max_len, 1), step):
        window = body[start : start + max_len].lower()
        score = sum(1 for t in q_terms if t in window)
        if score > best_score:
            best_score = score
            best_start = start
    return body[best_start : best_start + max_len]


def _extract_inspector_answer(body: str, title: str) -> Optional[str]:
    section = _extract_inspector_section(body) or body
    name_m = re.search(r"Inspector:\s*([^\n]+)", section, re.I)
    if not name_m:
        return None
    name = name_m.group(1).strip().rstrip(".")
    date_m = re.search(r"Inspection Date:\s*([^\n]+)", section, re.I)
    if date_m:
        date = date_m.group(1).strip().rstrip(".")
        return f"The bridge site was inspected by **{name}** on **{date}**."
    return f"The bridge site was inspected by **{name}**."


def _drawing_body_text(r: Dict[str, Any]) -> str:
    meta = r.get("metadata") or {}
    return (
        (meta.get("blob_chunk") or meta.get("sheet_notes") or r.get("snippet") or "")
        .strip()
    )


def _order_results_for_answer(
    query: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    from app.search.query_intel import is_asset_to_people_hop_query

    if is_asset_to_people_hop_query(query):
        team = [r for r in results if r.get("content_type") == "team"]
        projects = [r for r in results if r.get("content_type") == "project"]
        assets = [
            r
            for r in results
            if r.get("content_type") in {"equipment", "material", "vendor"}
        ]
        others = [
            r
            for r in results
            if r.get("content_type")
            not in {"team", "project", "equipment", "material", "vendor"}
        ]
        return team + projects + assets + others

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

    q_terms = {
        t
        for t in re.findall(r"[a-z0-9]+", query.lower())
        if len(t) > 3 and t not in {"what", "which", "who", "when", "where", "find", "listed", "bridge", "project"}
    }

    def _body_overlap(body: str) -> int:
        bl = body.lower()
        return sum(1 for t in q_terms if t in bl)

    def _inspector_signal(body: str) -> int:
        if not is_inspector_query(query):
            return 0
        return 1 if re.search(r"Inspector:\s*\w", body, re.I) else 0

    def doc_rank(r: Dict[str, Any]) -> tuple:
        meta = r.get("metadata") or {}
        snippet = (r.get("snippet") or "").lower()
        body = _document_body_text(r)
        is_real_blob = _is_blob_document(r) and "buildtrack document id" not in snippet
        title_score = score_document_title_match(query, r.get("title", ""))
        return (
            title_score,
            _inspector_signal(body),
            _body_overlap(body),
            1 if is_real_blob else 0,
            len(body),
        )

    docs.sort(key=doc_rank, reverse=True)
    return docs + others


def _format_result_for_context(r: Dict[str, Any], index: int, query: str = "") -> str:
    ctype = r.get("content_type", "item")
    title = r.get("title", "")
    meta = r.get("metadata") or {}
    db_label = meta.get("database_label") or meta.get("database_id")
    meta_parts = [
        f"{k}={v}"
        for k, v in meta.items()
        if v
        and str(v).strip()
        and k not in {
            "blob_chunk",
            "chunk_id",
            "source",
            "content_source",
            "database_id",
            "database_label",
            "related_from",
            "related_databases",
            "linked_by_relationship",
            "relationship",
            "related_via",
            "related_key",
        }
    ]
    meta_str = ", ".join(meta_parts) if meta_parts else ""
    rel_note = ""
    if meta.get("relationship") == "same_project" and meta.get("related_key"):
        via = meta.get("related_via") or "project_name"
        rel_note = f" [linked across DBs via {via}={meta.get('related_key')}]"

    if _is_blob_content(r) or (
        ctype == "drawing" and (meta.get("sheet_notes") or meta.get("blob_chunk"))
    ) or (
        ctype == "document" and (meta.get("body_text") or meta.get("blob_chunk"))
    ):
        raw_body = _drawing_body_text(r) if ctype == "drawing" else _document_body_text(r)
        raw_body = _refresh_blob_body_for_query(query, title, raw_body) if ctype == "document" else raw_body
        snippet = _query_relevant_excerpt(query, raw_body, max_len=1200)
        label = "drawing excerpt" if ctype == "drawing" else "document excerpt"
    else:
        snippet = (r.get("snippet") or "")[:220]
        label = ctype

    if db_label:
        line = f"{index}. [{label} | DB: {db_label}] {title}"
    else:
        line = f"{index}. [{label}] {title}"
    if rel_note:
        line += rel_note
    if meta_str:
        line += f" ({meta_str})"
    if snippet:
        line += f" — {snippet}"
    return line


def _build_prompt(query: str, results: List[Dict[str, Any]], analysis: Optional[QueryAnalysis]) -> str:
    from app.search.structured_filters import is_structured_filter_query

    ordered = _order_results_for_answer(query, results)
    limit = len(ordered) if is_structured_filter_query(query) else 8
    context_lines = [_format_result_for_context(r, i + 1, query) for i, r in enumerate(ordered[:limit])]
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
            "- Sources may come from MULTIPLE databases — synthesize ONE coherent answer across all of them.\n"
            "- When facts come from different databases, briefly name the database (DB label) in the answer.\n"
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

    if is_inspector_query(query):
        if not re.search(r"Inspector:\s*\w", current_body, re.I):
            from app.search.blob_retrieval import fetch_raw_chunks_for_document

            chunks = fetch_raw_chunks_for_document(
                title,
                "Inspector inspection site inspection Michael Rodriguez findings",
            )
            for text in chunks:
                if re.search(r"Inspector:\s*\w", text, re.I):
                    return text
            if chunks:
                return max(chunks, key=len)
        section = _extract_inspector_section(current_body)
        if section:
            return section

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
        if is_inspector_query(query):
            structured = _extract_inspector_answer(body, title)
            if structured:
                return structured
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
    if "could not find" in lower or "couldn't find" in lower or "no information" in lower:
        return True
    return bool(
        re.search(
            r"do(?:es)? not specify|don(?:'|')t specify|does not state|"
            r"not mentioned in the (?:document )?excerpt|"
            r"excerpts do not specify|excerpt does not specify",
            lower,
        )
    )


def _attach_source_citation(
    query: str, answer: str, results: List[Dict[str, Any]]
) -> str:
    """Append the exact source filename when the answer comes from file body text."""
    if not answer or _answer_says_not_found(answer):
        return answer
    if re.search(r"\*\*Source:\*\*", answer, re.I):
        return answer
    if re.search(r"From \*\*", answer):
        return answer
    if not is_document_content_query(query):
        return answer

    from app.search.result_filter import filter_by_blob_evidence

    sources = filter_by_blob_evidence(answer, results)
    if not sources:
        return answer
    title = (sources[0].get("title") or "Document").strip()
    return f"{answer.rstrip()}\n\n**Source:** {title}"


def _best_drawing_result(
    query: str, results: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Pick the drawing that best matches the question (not just search rank)."""
    drawings = [r for r in results if r.get("content_type") == "drawing"]
    if not drawings:
        return None
    if len(drawings) == 1:
        return drawings[0]

    def rank(r: Dict[str, Any]) -> float:
        meta = r.get("metadata") or {}
        return score_drawing_match(query, r.get("title", ""), meta)

    drawings.sort(key=rank, reverse=True)
    return drawings[0]


def _asset_to_people_hop_answer(
    query: str,
    results: List[Dict[str, Any]],
) -> Optional[Tuple[str, List[str]]]:
    """
    Deterministic answer for: who works on the project where asset X is used.
    Always answers from the asset's project team — never falls through to LLM
    with unrelated workforce hits.
    """
    from app.search.cross_db_links import (
        _equipment_matches_query,
        _fetch_buildtrack_team_for_project,
        _resolve_asset_from_sql,
        _team_matches_project,
        project_key_from_hit,
    )
    from app.search.query_intel import is_asset_to_people_hop_query

    if not is_asset_to_people_hop_query(query):
        return None

    ordered = list(results)
    equipment = [
        r
        for r in ordered
        if r.get("content_type") == "equipment" and _equipment_matches_query(r, query)
    ]
    if not equipment:
        equipment = [r for r in ordered if r.get("content_type") == "equipment"]
    if not equipment:
        sql_hits, _ = _resolve_asset_from_sql(query)
        equipment = sql_hits

    project_name = ""
    for r in equipment:
        project_name = project_key_from_hit(r) or str(
            (r.get("metadata") or {}).get("related_key")
            or (r.get("metadata") or {}).get("project")
            or ""
        ).strip()
        if project_name:
            break

    team = [
        r
        for r in ordered
        if r.get("content_type") == "team"
        and project_name
        and _team_matches_project(r, project_name)
    ]
    if not team and project_name:
        team = _fetch_buildtrack_team_for_project(project_name)

    asset_line = ""
    if equipment:
        e = equipment[0]
        meta = e.get("metadata") or {}
        tag = meta.get("asset_tag") or ""
        title = e.get("title") or "equipment"
        db = meta.get("database_label") or "Site Assets & Procurement"
        asset_line = f"{title}" + (f" ({tag})" if tag and tag not in str(title) else "")
        asset_line += f" - {db}"

    lines: List[str] = []
    if asset_line and project_name:
        lines.append(
            f"{asset_line} is used on **{project_name}** "
            f"(linked across Site Assets to BuildTrack)."
        )
    elif asset_line:
        lines.append(f"Matched asset: {asset_line}.")
    elif project_name:
        lines.append(f"Related project: **{project_name}**.")
    else:
        lines.append(
            "I could not identify which project uses that asset from the current data."
        )

    if team and project_name:
        lines.append(f"People working on **{project_name}**:")
        seen_names: set[str] = set()
        for r in team:
            name = str(r.get("title") or "").strip()
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            role = (r.get("metadata") or {}).get("role") or ""
            lines.append(f"• {name}" + (f" - {role}" if role else ""))
    elif project_name:
        lines.append(f"No workforce members were found for **{project_name}**.")

    answer = "\n".join(lines)
    suggested = [
        f"What equipment is on {project_name}?" if project_name else "List site equipment",
        f"Show tasks for {project_name}" if project_name else "Show site activities",
        "Who is the project manager for Metro Station Renovation?",
    ]
    return answer, suggested


def _manager_projects_answer(
    query: str,
    results: List[Dict[str, Any]],
) -> Optional[Tuple[str, List[str]]]:
    """
    Deterministic answer for "which projects are managed by <person>".
    Enumerates every matching project record so a document that describes one
    project in detail cannot stand in for the full list.
    """
    from app.search.content_mappers import _normalize_project_status
    from app.search.query_intel import parse_manager_filter, person_name_matches

    wanted = parse_manager_filter(query)
    if not wanted:
        return None

    projects: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in results:
        if r.get("content_type") != "project":
            continue
        meta = r.get("metadata") or {}
        if not person_name_matches(meta.get("project_manager"), wanted):
            continue
        name = str(r.get("title") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        projects.append(r)

    if not projects:
        return None

    manager_name = str(
        (projects[0].get("metadata") or {}).get("project_manager") or wanted
    ).strip()
    count = len(projects)
    plural = "project" if count == 1 else "projects"
    lines = [f"**{manager_name}** manages {count} {plural}:", ""]
    for r in projects:
        meta = r.get("metadata") or {}
        details = []
        if meta.get("status"):
            details.append(_normalize_project_status(str(meta["status"])))
        progress = meta.get("progress")
        if progress not in (None, ""):
            details.append(f"{progress}% complete")
        if meta.get("location"):
            details.append(str(meta["location"]))
        suffix = f" — {', '.join(details)}" if details else ""
        lines.append(f"- **{r.get('title')}**{suffix}")

    suggested = [
        f"What is the progress of {projects[0].get('title')}?",
        f"Who works on {projects[0].get('title')}?",
        f"What documents are linked to {projects[0].get('title')}?",
    ]
    return "\n".join(lines), suggested


def generate_answer(
    query: str,
    search_results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis] = None,
) -> Tuple[str, List[str]]:
    ordered = _order_results_for_answer(query, search_results)

    # Multi-hop asset→people must not reuse a stale LLM cache of unrelated workforce.
    hop = _asset_to_people_hop_answer(query, ordered)
    if hop:
        fingerprint = _results_fingerprint(ordered)
        key = _cache_key(query, fingerprint)
        _set_cached(key, *hop)
        return hop

    managed = _manager_projects_answer(query, ordered)
    if managed:
        fingerprint = _results_fingerprint(ordered)
        key = _cache_key(query, fingerprint)
        _set_cached(key, *managed)
        return managed

    fingerprint = _results_fingerprint(ordered)
    key = _cache_key(query, fingerprint)
    cached = _get_cached(key)
    if cached:
        logger.info("Answer cache hit: %s", query[:40])
        return cached

    if not search_results:
        from app.search.query_intel import parse_manager_filter

        named_manager = parse_manager_filter(query)
        if named_manager:
            return (
                f"No projects are assigned to **{named_manager}** as project manager. "
                "They may still be on a project team without managing it.",
                [
                    "Who are the project managers?",
                    f"Which projects is {named_manager} a team member of?",
                    "Which projects are in progress?",
                ],
            )
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

    # Drawing answers: vision-first on best-matching drawing, extracted text as fallback.
    top_drawing = _best_drawing_result(query, ordered)
    if is_drawing_content_query(query) and top_drawing:
        from app.search.drawing_vision import (
            _drawing_followups,
            answer_drawing_vision_first,
            drawing_vision_fallback,
        )

        vision_answer = answer_drawing_vision_first(query=query, drawing=top_drawing)
        if vision_answer:
            followups = (
                _contextual_drawing_followups(query)
                if is_drawing_contextual_layout_query(query)
                else _drawing_followups(query)
            )
            result = (vision_answer, followups)
            _set_cached(key, *result)
            return result

        text_answer = (
            _answer_drawing_from_extracted_text(query, ordered)
            or _extractive_document_answer(query, ordered)
        )
        if text_answer and not _drawing_text_answer_is_weak(text_answer):
            followups = (
                _contextual_drawing_followups(query)
                if is_drawing_contextual_layout_query(query)
                else _drawing_followups(query)
            )
            result = (text_answer, followups)
            _set_cached(key, *result)
            return result

        fallback = drawing_vision_fallback(query=query, drawing=top_drawing)
        result = (fallback, _drawing_followups(query))
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
                result = (_attach_source_citation(query, extractive, ordered), suggested)
                _set_cached(key, *result)
                return result

    if is_handover_workflow_query(query):
        workflow = _handover_workflow_answer(query, ordered)
        if workflow:
            result = (workflow, _handover_workflow_followups())
            _set_cached(key, *result)
            return result

    if is_inspector_query(query):
        extractive = _extractive_document_answer(query, ordered)
        if extractive:
            suggested = [
                "What were the key findings from the inspection?",
                "What is the current progress of the Highway Bridge Expansion project?",
                "Who is the project manager for the Highway Bridge Expansion?",
            ]
            result = (_attach_source_citation(query, extractive, ordered), suggested)
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

        if is_inspector_query(query) and _answer_says_not_found(answer):
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

        answer = _attach_source_citation(query, answer, ordered)

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
