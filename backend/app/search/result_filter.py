"""Narrow search dropdown results to items relevant to the query and AI answer."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.search.query_intel import (
    QueryAnalysis,
    extract_drawing_no,
    is_which_drawing_query,
    is_workforce_aggregate_query,
    extract_project_qualifier,
    score_document_title_match,
    score_drawing_match,
)

_DRAWING_NO_RE = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z0-9]\b", re.I)

_QUERY_STOP = frozenset({
    "find", "show", "list", "tell", "give", "what", "which", "where", "when",
    "how", "does", "that", "this", "with", "from", "have", "has", "been",
    "drawing", "drawings", "document", "documents", "shows", "showing",
    "please", "could", "would", "there", "about", "your", "mine",
})

_TEAM_ROLE_PATTERNS: list[tuple[str, str]] = [
    (r"\bproject\s+managers?\b", "project_manager"),
    (r"\bsite\s+engineers?\b", "site_engineer"),
    (r"\bcontractors?\b", "contractor"),
    (r"\badmins?\b", "admin"),
]

_GENERIC_ENTITIES = frozenset({
    "pending", "submitted", "approved", "signed", "open", "closed",
    "project", "projects", "document", "documents", "drawing", "drawings",
    "task", "tasks", "team", "workforce", "safety", "handover",
    "metro station renovation", "highway bridge expansion",
})


def extract_team_role_filter(query: str) -> Optional[str]:
    """Return a role slug when the query asks for a specific workforce role."""
    q = query.lower()
    for pattern, role in _TEAM_ROLE_PATTERNS:
        if re.search(pattern, q):
            return role
    return None


def _normalize_role(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def _role_matches_result(result: Dict[str, Any], role_slug: str) -> bool:
    if result.get("content_type") != "team":
        return False
    meta = result.get("metadata") or {}
    result_role = _normalize_role(str(meta.get("role", "")))
    target = _normalize_role(role_slug)
    if result_role == target:
        return True
    display = role_slug.replace("_", " ")
    snippet = (result.get("snippet") or "").lower()
    return display in snippet


def _is_valid_entity(text: str) -> bool:
    lower = text.lower().strip().rstrip(":")
    if len(lower) < 3:
        return False
    if lower.startswith(
        ("based on", "the user", "no results", "i couldn't", "i could not", "try ", "next steps")
    ):
        return False
    if lower in _GENERIC_ENTITIES:
        return False
    return True


def _extract_answer_entities(answer: str) -> Set[str]:
    entities: Set[str] = set()
    if not answer:
        return entities

    for match in re.finditer(r"\*\*([^*]+)\*\*", answer):
        text = match.group(1).strip()
        if _is_valid_entity(text):
            entities.add(text)

    for match in _DRAWING_NO_RE.finditer(answer):
        entities.add(match.group(0).upper())

    for match in re.finditer(r"\*\*Drawing:\*\*\s*(.+?)(?:\n|$)", answer, re.I):
        text = match.group(1).strip().rstrip(".")
        if _is_valid_entity(text):
            entities.add(text)
        for num in _DRAWING_NO_RE.finditer(text):
            entities.add(num.group(0).upper())

    for match in re.finditer(
        r"(?:Drawing\s+No\.?|Drawing\s+number|Title)\s*:\s*(.+?)(?:\n|$)",
        answer,
        re.I,
    ):
        text = match.group(1).strip().rstrip(".")
        if _is_valid_entity(text):
            entities.add(text)

    for line in answer.splitlines():
        stripped = line.strip().lstrip("-•* ").strip()
        if not stripped:
            continue
        stripped = re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
        name_match = re.match(r"^([^(\n—–:]+)", stripped)
        if not name_match:
            continue
        candidate = re.sub(r"\*+", "", name_match.group(1)).strip()
        if _is_valid_entity(candidate):
            entities.add(candidate)

    return entities


def _name_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _entity_matches_result(entity: str, result: Dict[str, Any]) -> bool:
    el = entity.lower().strip()
    if len(el) < 3 or el in _GENERIC_ENTITIES:
        return False

    meta = result.get("metadata") or {}
    drawing_no = str(meta.get("drawing_no") or "").upper()
    if _DRAWING_NO_RE.fullmatch(entity.strip()):
        if drawing_no and drawing_no.upper() == entity.strip().upper():
            return True
        if entity.strip().upper() in (result.get("title") or "").upper():
            return True

    title = (result.get("title") or "").lower()
    if el in title or title in el:
        return True

    entity_tokens = _name_tokens(el)
    title_tokens = _name_tokens(title)
    if entity_tokens and entity_tokens <= title_tokens:
        return True

    haystack = " ".join(
        [
            result.get("snippet") or "",
            " ".join(str(v) for v in (result.get("metadata") or {}).values()),
        ]
    ).lower()
    if el in haystack:
        return True

    if len(entity_tokens) >= 2 and entity_tokens <= _name_tokens(haystack):
        return True

    return False


def _blob_body_text(result: Dict[str, Any]) -> str:
    meta = result.get("metadata") or {}
    return (meta.get("blob_chunk") or result.get("snippet") or "").strip()


def _is_internal_crawl_sidecar(result: Dict[str, Any]) -> bool:
    """
    RAG text sidecars (e.g. AR-113-9_sheet_content.txt) are for search indexing only.
    Users should see the real drawing/document file in the dropdown, not the sidecar.
    """
    title = (result.get("title") or "").lower()
    meta = result.get("metadata") or {}
    filename = str(
        meta.get("filename")
        or meta.get("original_filename")
        or meta.get("blob_name")
        or ""
    ).lower()
    blob = str(meta.get("blob_url") or meta.get("file_url") or "").lower()
    hay = " ".join([title, filename, blob])
    if "_sheet_content.txt" in hay or " sheet content.txt" in hay:
        return True
    if meta.get("sidecar") in ("drawing_crawl", "document_body", "sheet_content"):
        return True
    if "sheet content" in title and extract_drawing_no(title):
        return True
    return False


def _matches_drawing_number(result: Dict[str, Any], drawing_no: str) -> bool:
    if not drawing_no:
        return False
    meta = result.get("metadata") or {}
    dno = str(meta.get("drawing_no") or "").upper()
    title = (result.get("title") or "").upper()
    return dno == drawing_no or drawing_no in title


def _prefer_drawing_rows(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop crawl sidecars; when a real drawing row exists, show only that."""
    visible = [r for r in results if not _is_internal_crawl_sidecar(r)]
    drawings = [r for r in visible if r.get("content_type") == "drawing"]
    return drawings if drawings else visible


def _filter_to_named_drawing(
    query: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """When the user names a drawing number, keep only that drawing file."""
    named = extract_drawing_no(query)
    if not named:
        return []
    matched = [r for r in results if _matches_drawing_number(r, named)]
    return _prefer_drawing_rows(matched)


def _filter_by_answer_drawing_numbers(
    answer: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    numbers = {m.group(0).upper() for m in _DRAWING_NO_RE.finditer(answer or "")}
    if not numbers:
        return []

    matched: List[Dict[str, Any]] = []
    for r in results:
        if any(_matches_drawing_number(r, num) for num in numbers):
            matched.append(r)
    return _prefer_drawing_rows(matched)


def _extract_evidence_terms(answer: str) -> Set[str]:
    """Terms from the AI answer that should appear in the source file body."""
    terms: Set[str] = set()
    if not answer:
        return terms

    for match in re.finditer(r"\*\*([^*]+)\*\*", answer):
        text = match.group(1).strip()
        if text.lower() in {"source", "drawing"} or text.lower().startswith("source"):
            continue
        if len(text) > 2:
            terms.add(text.lower())

    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", answer):
        terms.add(match.group(1).lower())

    for match in re.finditer(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}\b",
        answer,
        re.I,
    ):
        terms.add(match.group(0).lower())

    for line in answer.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "•", "*")) and len(stripped) > 4:
            item = re.sub(r"^[-•*]\s*", "", stripped)
            item = re.sub(r"\*\*([^*]+)\*\*", r"\1", item).strip()
            if len(item) > 3:
                terms.add(item.lower())

    return {t for t in terms if len(t) > 3 and t not in _GENERIC_ENTITIES}


def filter_by_blob_evidence(
    answer: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Keep only file hits whose indexed body text supports the AI answer.
    Returns best match(es) first — typically the single source document.
    """
    terms = _extract_evidence_terms(answer)
    if not terms:
        return []

    strong = {t for t in terms if len(t.split()) >= 2 or re.search(r"\d{4}", t)}

    scored: list[tuple[int, int, float, Dict[str, Any]]] = []
    for r in results:
        if _is_internal_crawl_sidecar(r):
            continue
        ctype = r.get("content_type")
        if ctype not in ("document", "drawing"):
            continue
        body = _blob_body_text(r).lower()
        if len(body) < 30:
            continue
        if "upload or sync a real pdf" in body:
            continue

        hits = sum(1 for t in terms if t in body)
        strong_hits = sum(1 for t in strong if t in body)
        if strong_hits >= 1 or hits >= 2:
            scored.append((strong_hits, hits, float(r.get("score") or 0), r))

    if not scored:
        return []

    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    best_strong, best_hits, _, _ = scored[0]
    matched = [
        r
        for sh, h, _, r in scored
        if sh == best_strong and h == best_hits
    ]
    return _prefer_drawing_rows(matched)


def _filter_by_answer_entities(
    answer: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    entities = _extract_answer_entities(answer)
    if not entities:
        return []

    matched = [r for r in results if any(_entity_matches_result(e, r) for e in entities)]
    if not matched:
        return []

    # Prefer results that match more entities / stronger title hits
    def rank(r: Dict[str, Any]) -> tuple:
        title = (r.get("title") or "").lower()
        hits = sum(1 for e in entities if _entity_matches_result(e, r))
        exact = any(e.lower() == title for e in entities)
        return (hits, 1 if exact else 0, float(r.get("score") or 0))

    matched.sort(key=rank, reverse=True)
    return matched


def _extract_query_subject_terms(query: str) -> set[str]:
    q = query.lower()
    terms: set[str] = set()
    for phrase in (
        "floor plan", "master plan", "residential unit", "studio apartment",
        "site plan", "screw conveyor", "cross section", "weld detail",
        "office furniture", "office workstation",
    ):
        if phrase in q:
            terms.update(t for t in phrase.split() if len(t) > 3)
    for tok in re.findall(r"[a-z0-9]+", q):
        if len(tok) > 3 and tok not in _QUERY_STOP and tok not in _GENERIC_ENTITIES:
            terms.add(tok)
    return terms


_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "furniture": ("workstation", "desk", "chair", "office", "conference", "table"),
    "office": ("workstation", "conference"),
}


def _term_in_haystack(term: str, haystack: str) -> bool:
    if term in haystack:
        return True
    return any(alias in haystack for alias in _TERM_ALIASES.get(term, ()))


def _result_query_relevance(query: str, result: Dict[str, Any]) -> float:
    meta = result.get("metadata") or {}
    title = result.get("title") or ""
    snippet = result.get("snippet") or ""
    ctype = result.get("content_type") or ""
    haystack = " ".join(
        [title, snippet, " ".join(str(v) for v in meta.values())]
    ).lower()

    score = float(result.get("score") or 0) * 0.05

    if ctype == "drawing":
        score += score_drawing_match(query, title, meta)
    elif ctype == "document":
        score += score_document_title_match(query, title) * 0.6

    terms = _extract_query_subject_terms(query)
    if terms:
        hits = sum(1 for t in terms if _term_in_haystack(t, haystack))
        score += (hits / len(terms)) * 35.0

    named_drawing = extract_drawing_no(query)
    if named_drawing:
        if str(meta.get("drawing_no", "")).upper() == named_drawing:
            score += 80.0
        elif named_drawing.lower() in title.lower():
            score += 60.0

    return score


def _filter_by_query_relevance(
    query: str,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Drop clearly irrelevant hits; keep every result that genuinely matches the question.
    No fixed cap — if three drawings all match 'residential apartment', show all three.
    """
    if len(results) <= 1:
        return results

    scored = [(r, _result_query_relevance(query, r)) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)
    top_score = scored[0][1]
    if top_score <= 5.0:
        return results

    ratio = 0.72 if is_which_drawing_query(query) else 0.55
    min_score = max(8.0, top_score * ratio)
    filtered = [r for r, s in scored if s >= min_score and s > 0]

    terms = _extract_query_subject_terms(query)
    if terms and filtered:
        term_matched: List[Dict[str, Any]] = []
        for r in filtered:
            meta = r.get("metadata") or {}
            haystack = " ".join(
                [r.get("title") or "", r.get("snippet") or "",
                 " ".join(str(v) for v in meta.values())]
            ).lower()
            hits = sum(1 for t in terms if _term_in_haystack(t, haystack))
            min_hits = 2 if len(terms) >= 2 and is_which_drawing_query(query) else 1
            if hits >= min_hits:
                term_matched.append(r)
        if term_matched:
            filtered = term_matched

    return filtered if filtered else [scored[0][0]]


def _filter_by_team_role(
    results: List[Dict[str, Any]], role_slug: str, project_qualifier: Optional[str] = None
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    qual = (project_qualifier or "").lower()
    for r in results:
        if not _role_matches_result(r, role_slug):
            continue
        if qual:
            meta = r.get("metadata") or {}
            projects = meta.get("projects") or []
            if isinstance(projects, str):
                projects = [projects]
            proj_text = " ".join(str(p) for p in projects).lower()
            snippet = (r.get("snippet") or "").lower()
            if qual not in proj_text and qual not in snippet:
                if not any(w in proj_text for w in qual.split() if len(w) > 3):
                    continue
        filtered.append(r)
    return filtered


_ASSET_KIND_PATTERNS: list[tuple[str, str]] = [
    (r"\bcranes?\b", "crane"),
    (r"\bexcavators?\b", "excavator"),
    (r"\bgenerators?\b", "generator"),
    (r"\bscaffolds?(?:ing)?\b", "scaffold"),
    (r"\bboom\s*lifts?\b", "boom lift"),
    (r"\bconcrete\s*pumps?\b", "concrete pump"),
    (r"\bpumps?\b", "pump"),
    (r"\bppe\b|\bhelmets?\b|\bhigh[- ]vis", "ppe"),
]


def extract_asset_kind(query: str) -> Optional[str]:
    """Specific equipment/material kind asked about, e.g. 'crane'."""
    q = query.lower()
    for pattern, kind in _ASSET_KIND_PATTERNS:
        if re.search(pattern, q):
            return kind
    return None


def _asset_haystack(result: Dict[str, Any]) -> str:
    meta = result.get("metadata") or {}
    parts = [
        result.get("title") or "",
        result.get("snippet") or "",
        str(meta.get("category") or ""),
        str(meta.get("project") or ""),
        str(meta.get("vendor") or ""),
        str(meta.get("asset_tag") or ""),
        str(meta.get("name") or ""),
    ]
    return " ".join(parts).lower()


def _matches_asset_kind(result: Dict[str, Any], kind: str) -> bool:
    if not kind:
        return True
    hay = _asset_haystack(result)
    return all(tok in hay for tok in kind.split() if tok)


def _matches_asset_project(result: Dict[str, Any], project_qual: str) -> bool:
    if not project_qual:
        return True
    hay = _asset_haystack(result)
    qual = project_qual.lower().strip()
    if qual in hay:
        return True
    words = [w for w in qual.split() if len(w) > 3]
    if not words:
        return True
    hits = sum(1 for w in words if w in hay)
    return hits >= max(2, (len(words) + 1) // 2)


def _dedupe_asset_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for r in results:
        key = f"{r.get('content_type')}|{str(r.get('title') or '').strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def _filter_asset_inventory_results(
    query: str,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Keep only assets that match the asked equipment/material kind and project.
    Example: 'What crane is on Highway Bridge Expansion?' → CRN-220 (+ related crane vendor),
    not excavators on Metro or unrelated PPE kits.
    """
    kind = extract_asset_kind(query)
    project = extract_project_qualifier(query)
    q = query.lower()

    wants_vendor = bool(re.search(r"\b(vendor|supplier|who\s+supplies|rentals?)\b", q))
    wants_material = bool(re.search(r"\b(material|deliver(?:y|ies)|ppe|helmet|vest)\b", q))
    # Default for "what crane is on …" is equipment
    wants_equipment = (
        bool(kind)
        or bool(re.search(r"\b(equipment|machinery|asset)\b", q))
        or (not wants_vendor and not wants_material)
    )

    equipment = [r for r in results if r.get("content_type") == "equipment"]
    vendors = [r for r in results if r.get("content_type") == "vendor"]
    materials = [r for r in results if r.get("content_type") == "material"]

    out: List[Dict[str, Any]] = []

    if wants_equipment:
        matched = [
            r
            for r in equipment
            if _matches_asset_kind(r, kind or "")
            and _matches_asset_project(r, project or "")
        ]
        if not matched and kind:
            # Kind matched but project missing — still show that equipment type only
            matched = [r for r in equipment if _matches_asset_kind(r, kind)]
            if project:
                proj_hit = [r for r in matched if _matches_asset_project(r, project)]
                if proj_hit:
                    matched = proj_hit
        out.extend(matched)

    if wants_vendor or (kind and out):
        # Related vendor only when it matches the same kind (e.g. "Crane Rentals")
        for r in vendors:
            if kind and not _matches_asset_kind(r, kind):
                continue
            out.append(r)
        # If the question is specifically about equipment on a project, keep at most
        # one supporting vendor when we already have the equipment hit.
        if wants_equipment and not wants_vendor and out:
            equip = [r for r in out if r.get("content_type") == "equipment"]
            vend = [r for r in out if r.get("content_type") == "vendor"]
            if equip:
                out = equip + vend[:1]

    if wants_material:
        matched_m = [
            r
            for r in materials
            if _matches_asset_kind(r, kind or "")
            and _matches_asset_project(r, project or "")
        ]
        if not matched_m and kind:
            matched_m = [r for r in materials if _matches_asset_kind(r, kind)]
        out.extend(matched_m)

    out = _dedupe_asset_results(out)
    if out:
        return out
    # Last resort: best single equipment/vendor match by kind
    if kind:
        loose = [r for r in results if _matches_asset_kind(r, kind)]
        loose = _dedupe_asset_results(loose)
        if loose:
            return loose[:3]
    return _dedupe_asset_results(
        [r for r in results if r.get("content_type") in {"equipment", "vendor", "material"}]
    )[:5]


def filter_results_for_query(
    query: str,
    results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis] = None,
) -> List[Dict[str, Any]]:
    """Pre-filter results for fast /results before the AI answer is ready."""
    if not results:
        return results

    from app.search.structured_filters import is_structured_filter_query
    from app.search.query_intel import is_asset_inventory_query

    if is_structured_filter_query(query) or is_workforce_aggregate_query(query):
        return results

    # Explicit drawing number in the query → only that sheet in the dropdown
    named_only = _filter_to_named_drawing(query, results)
    if named_only:
        return named_only

    role = extract_team_role_filter(query)
    if role:
        project_qual = extract_project_qualifier(query)
        role_filtered = _filter_by_team_role(results, role, project_qual)
        if role_filtered:
            return role_filtered
        # Role was explicit — never fall through to budget/report docs.
        team_only = [r for r in results if r.get("content_type") == "team"]
        return team_only
    # Exception: asset→people hop queries must keep team + project hits.
    from app.search.query_intel import is_asset_to_people_hop_query

    if is_asset_to_people_hop_query(query):
        # Strict: only equipment matching the asked asset + team/project for THAT project.
        from app.search.cross_db_links import (
            _equipment_matches_query,
            _team_matches_project,
            project_key_from_hit,
        )

        equipment = [
            r
            for r in results
            if r.get("content_type") in {"equipment", "material"}
            and _equipment_matches_query(r, query)
        ]
        if not equipment:
            equipment = [
                r for r in results if r.get("content_type") in {"equipment", "material"}
            ]
        asset_projects = {
            project_key_from_hit(r)
            for r in equipment
            if project_key_from_hit(r)
        }
        for r in equipment:
            rk = (r.get("metadata") or {}).get("related_key")
            if rk:
                asset_projects.add(str(rk))

        team = [
            r
            for r in results
            if r.get("content_type") == "team"
            and any(_team_matches_project(r, p) for p in asset_projects)
        ]
        projects = [
            r
            for r in results
            if r.get("content_type") == "project"
            and project_key_from_hit(r) in asset_projects
        ]
        merged_hop: list = []
        seen: set[str] = set()
        for r in team + equipment + projects:
            rid = str(r.get("id") or "")
            if rid in seen:
                continue
            if rid:
                seen.add(rid)
            merged_hop.append(r)
        return merged_hop or equipment or results

    if is_asset_inventory_query(query):
        return _filter_asset_inventory_results(query, results)

    filtered = results
    if analysis and analysis.is_question and len(analysis.content_types) == 1:
        primary = analysis.content_types[0]
        type_filtered = [r for r in filtered if r.get("content_type") == primary]
        if type_filtered:
            filtered = type_filtered

    if analysis and analysis.is_question:
        relevance = _filter_by_query_relevance(query, filtered)
        if relevance:
            return relevance

    return filtered


def _answer_says_not_found(answer: str) -> bool:
    lower = answer.lower().strip()
    if not lower:
        return False
    if lower in {"i could not find it.", "not found.", "none.", "n/a"}:
        return True
    return bool(
        re.search(
            r"\b(could not find|couldn't find|cannot find|can't find|"
            r"no information|not found|not mentioned|not stated|not visible|"
            r"do(?:es)? not specify|don(?:'|')t specify|excerpts do not specify|"
            r"no (?:evidence|record|data|results?))\b",
            lower,
        )
    )


def filter_results_for_display(
    query: str,
    answer: str,
    results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis] = None,
) -> List[Dict[str, Any]]:
    """Filter dropdown results to match what the AI answer actually covers."""
    if not results:
        return results

    if is_workforce_aggregate_query(query):
        return results

    # Explicit drawing number → only that drawing (even before blob evidence)
    named_only = _filter_to_named_drawing(query, results)
    if named_only:
        return named_only

    role = extract_team_role_filter(query)
    if role:
        project_qual = extract_project_qualifier(query)
        role_filtered = _filter_by_team_role(results, role, project_qual)
        if role_filtered:
            return role_filtered
        # Role was explicit — never fall through to budget/report docs.
        team_only = [r for r in results if r.get("content_type") == "team"]
        return team_only

    if answer and answer.strip():
        if _answer_says_not_found(answer):
            return []

        # Answer cites specific drawing number(s) → only those sheets
        drawing_filtered = _filter_by_answer_drawing_numbers(answer, results)
        if drawing_filtered:
            return drawing_filtered

        from app.search.query_intel import (
            is_asset_inventory_query,
            is_asset_to_people_hop_query,
            is_document_content_query,
            is_drawing_content_query,
        )

        if is_asset_to_people_hop_query(query):
            # Keep people answer evidence; don't collapse to equipment-only.
            return filter_results_for_query(query, results, analysis)

        if is_asset_inventory_query(query):
            precise = _filter_asset_inventory_results(query, results)
            if precise:
                # Further narrow to items the answer actually cites when possible.
                entity_filtered = _filter_by_answer_entities(answer, precise)
                return entity_filtered if entity_filtered else precise
            return results

        if is_document_content_query(query) or is_drawing_content_query(query):
            evidence_filtered = filter_by_blob_evidence(answer, results)
            if evidence_filtered:
                return evidence_filtered

        entity_filtered = _filter_by_answer_entities(answer, results)
        if entity_filtered:
            return entity_filtered

        # Substantive answer but no named entities — keep all query-relevant hits
        if analysis and analysis.is_question:
            relevance = _filter_by_query_relevance(query, results)
            if len(relevance) < len(results):
                return relevance
            from app.search.query_intel import is_document_content_query, is_drawing_content_query

            if is_document_content_query(query) or is_drawing_content_query(query):
                return relevance if relevance else []

    from app.search.structured_filters import is_structured_filter_query

    if is_structured_filter_query(query):
        return results

    return filter_results_for_query(query, results, analysis)
