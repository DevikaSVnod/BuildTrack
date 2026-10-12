"""SPACE AI answer — same idea as the POC /search/answer path.

Azure OpenAI summarises only the Top-K rows already returned by module APIs
(ACL trimmed). Keys stay on the server. Do not log the query text or titles.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Sequence

from app.core.config import settings
from global_search_core.models import SearchResultItem

log = logging.getLogger("space-answer")

QUESTION_STARTERS = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "which",
    "list",
    "show",
    "find",
    "tell",
)


def looks_like_question(query: str) -> bool:
    q = re.sub(r"\s+", " ", query.strip().lower())
    if not q:
        return False
    if q.endswith("?"):
        return True
    return any(q == starter or q.startswith(starter + " ") for starter in QUESTION_STARTERS)


def _rows(results: Sequence[SearchResultItem] | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in results:
        if isinstance(item, SearchResultItem):
            out.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "snippet": item.snippet,
                    "content_type": item.content_type,
                    "metadata": item.metadata or {},
                }
            )
        elif isinstance(item, dict):
            out.append(item)
    return out[:8]


def _fallback_answer(query: str, rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not rows:
        return (
            "No matching SPACE records were found for this search.",
            ["events", "contracts", "documents"],
        )
    lines = ["Here is what matched in SPACE:"]
    for row in rows[:5]:
        label = (row.get("metadata") or {}).get("entityLabel") or row.get("content_type") or "record"
        title = str(row.get("title") or row.get("id") or "").strip()
        snippet = str(row.get("snippet") or "").strip()
        extra = f" — {snippet}" if snippet else ""
        lines.append(f"• {label}: {title}{extra}")
    return "\n".join(lines), ["events", "contracts", "documents"]


def generate_space_answer(
    query: str,
    results: Sequence[SearchResultItem] | Iterable[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Return (answer, suggested_questions). Never raises to the caller."""
    rows = _rows(results)
    if not rows:
        return _fallback_answer(query, rows)
    if not (settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_KEY):
        return _fallback_answer(query, rows)

    sources = []
    for i, row in enumerate(rows, start=1):
        label = (row.get("metadata") or {}).get("entityLabel") or row.get("content_type") or "record"
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or "").strip()
        sources.append(f"{i}. [{label}] {title}" + (f" — {snippet}" if snippet else ""))
    source_block = "\n".join(sources) if sources else "No matching records."

    prompt = (
        "You are the SPACE search assistant for Shapoorji Pallonji SPACE.\n"
        "Answer ONLY using the SOURCES below (Meetings, Contracts, Documents, "
        "Incidents, Checklists the user is allowed to see).\n"
        "Do not invent records. Do not mention BuildTrack. Do not output URLs.\n"
        "If the sources are empty, say nothing matched.\n"
        "If sources are listed, summarise those records against the user query. "
        "Do not say nothing matched while sources are present.\n"
        "Return JSON with keys answer (string) and questions (array of up to 3 short follow-ups).\n\n"
        f"USER QUERY LENGTH: {len(query.strip())}\n"
        f"USER QUERY: {query.strip()}\n\n"
        f"SOURCES:\n{source_block}\n"
    )

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        response = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": "You answer using only provided SPACE sources. Return valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        answer = parsed.get("answer", "")
        if isinstance(answer, list):
            answer = "\n".join(str(x).strip() for x in answer if str(x).strip())
        answer = str(answer).strip()
        suggested = parsed.get("questions", [])
        if not isinstance(suggested, list):
            suggested = []
        suggested = [str(q).strip() for q in suggested if str(q).strip()][:3]
        if not answer:
            return _fallback_answer(query, rows)
        return answer, suggested
    except Exception:
        log.warning("space openai answer failed", extra={"errorCode": "space_openai_failed"})
        return _fallback_answer(query, rows)
