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

_DRAWING_NO_RE = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z]\b", re.I)

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


def _filter_by_answer_drawing_numbers(
    answer: str, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    numbers = {m.group(0).upper() for m in _DRAWING_NO_RE.finditer(answer or "")}
    if not numbers:
        return []

    matched: List[Dict[str, Any]] = []
    for r in results:
        meta = r.get("metadata") or {}
        drawing_no = str(meta.get("drawing_no") or "").upper()
        title = (r.get("title") or "").upper()
        if drawing_no in numbers or any(num in title for num in numbers):
            matched.append(r)
    return matched


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


def filter_results_for_query(
    query: str,
    results: List[Dict[str, Any]],
    analysis: Optional[QueryAnalysis] = None,
) -> List[Dict[str, Any]]:
    """Pre-filter results for fast /results before the AI answer is ready."""
    if not results:
        return results

    from app.search.structured_filters import is_structured_filter_query

    if is_structured_filter_query(query) or is_workforce_aggregate_query(query):
        return results

    role = extract_team_role_filter(query)
    if role:
        project_qual = extract_project_qualifier(query)
        role_filtered = _filter_by_team_role(results, role, project_qual)
        if role_filtered:
            return role_filtered

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

    role = extract_team_role_filter(query)
    if role:
        project_qual = extract_project_qualifier(query)
        role_filtered = _filter_by_team_role(results, role, project_qual)
        if role_filtered:
            return role_filtered

    if answer and answer.strip():
        if _answer_says_not_found(answer):
            return []

        drawing_filtered = _filter_by_answer_drawing_numbers(answer, results)
        if drawing_filtered:
            return drawing_filtered

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
