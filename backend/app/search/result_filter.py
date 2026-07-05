"""Narrow search dropdown results to items relevant to the query and AI answer."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.search.query_intel import (
    QueryAnalysis,
    is_workforce_aggregate_query,
    extract_project_qualifier,
)

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

    if analysis and analysis.is_question and len(analysis.content_types) == 1:
        primary = analysis.content_types[0]
        type_filtered = [r for r in results if r.get("content_type") == primary]
        if type_filtered and len(type_filtered) < len(results):
            return type_filtered

    return results


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

        entity_filtered = _filter_by_answer_entities(answer, results)
        if entity_filtered:
            return entity_filtered

        # Substantive answer but no named entities — drop unrelated hits for Q&A queries
        if analysis and analysis.is_question:
            from app.search.query_intel import is_document_content_query, is_drawing_content_query

            if is_document_content_query(query) or is_drawing_content_query(query):
                return []

    from app.search.structured_filters import is_structured_filter_query

    if is_structured_filter_query(query):
        return results

    return filter_results_for_query(query, results, analysis)
