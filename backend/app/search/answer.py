from typing import List, Dict, Any, Tuple, Optional

from app.core.config import settings

from app.search.query_intel import QueryAnalysis, is_question

import json

import time

import hashlib

import logging



logger = logging.getLogger(__name__)



_answer_cache: Dict[str, Tuple[float, str, List[str]]] = {}

CACHE_TTL = 300





def _cache_key(query: str, results_fingerprint: str) -> str:

    raw = f"{query.strip().lower()}|{results_fingerprint}"

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





def _format_result_for_context(r: Dict[str, Any], index: int) -> str:

    ctype = r.get("content_type", "item")

    title = r.get("title", "")

    meta = r.get("metadata") or {}

    meta_parts = [f"{k}={v}" for k, v in meta.items() if v and str(v).strip()]

    meta_str = ", ".join(meta_parts) if meta_parts else ""

    snippet = (r.get("snippet") or "")[:200]

    line = f"{index}. [{ctype}] {title}"

    if meta_str:

        line += f" ({meta_str})"

    if snippet:

        line += f" — {snippet}"

    return line





def _build_prompt(query: str, results: List[Dict[str, Any]], analysis: Optional[QueryAnalysis]) -> str:
    from app.search.structured_filters import is_structured_filter_query

    # Filter queries may return >8 exact matches — include all for accurate AI answers.
    limit = len(results) if is_structured_filter_query(query) else 8
    context_lines = [_format_result_for_context(r, i + 1) for i, r in enumerate(results[:limit])]

    context = "\n".join(context_lines) if context_lines else "No matching records."



    question_mode = analysis.is_question if analysis else is_question(query)

    domain_note = ""

    if analysis and analysis.content_types:

        domain_note = f"User is asking about: {', '.join(analysis.content_types)}. "

    if analysis and analysis.status_hints:

        domain_note += f"Filter focus: {', '.join(analysis.status_hints)}. "



    if question_mode:

        return (

            "You are BuildTrack AI, an expert assistant for a construction site management platform "

            "(projects, site activities, DMS documents, handover closeout, drawings, safety/HSE, workforce).\n\n"

            "RULES:\n"

            "- Answer ONLY using the SOURCES below. If the answer is not in sources, say you could not find it in the system.\n"

            "- Be direct and specific: name titles, statuses, projects, and people when relevant.\n"

            "- For list questions, use a short bullet list in the answer field.\n"

            "- Do not mention Azure, search indexes, or AI.\n"

            f"{domain_note}\n"

            f"SOURCES:\n{context}\n\n"

            f"USER QUESTION: {query}\n\n"

            "Respond with JSON only:\n"

            '{"answer": "<clear accurate answer, 2-5 sentences or bullets>", '

            '"questions": ["<follow-up 1>", "<follow-up 2>", "<follow-up 3>"]}'

        )



    return (

        "You are BuildTrack AI for a construction project management platform.\n"

        f"Sources:\n{context}\n\n"

        f"User searched: {query}\n\n"

        "Summarize what was found in 1-2 sentences. JSON only:\n"

        '{"answer": "<summary>", "questions": ["q1", "q2", "q3"]}'

    )





def generate_answer(

    query: str,

    search_results: List[Dict[str, Any]],

    analysis: Optional[QueryAnalysis] = None,

) -> Tuple[str, List[str]]:

    fingerprint = _results_fingerprint(search_results)

    key = _cache_key(query, fingerprint)

    cached = _get_cached(key)

    if cached:

        logger.info(f"Answer cache hit: {query[:40]}")

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

        return _fallback_answer(query, search_results, analysis)



    try:

        from openai import AzureOpenAI

        client = AzureOpenAI(

            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,

            api_key=settings.AZURE_OPENAI_KEY,

            api_version="2024-02-01",

        )



        prompt = _build_prompt(query, search_results, analysis)

        question_mode = analysis.is_question if analysis else is_question(query)

        max_tokens = 450 if question_mode else 280



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

        answer = parsed.get("answer", "").strip()

        suggested = parsed.get("questions", [])

        if not isinstance(suggested, list):

            suggested = []



        if not answer:

            answer = _grounded_answer(query, search_results, analysis)



        result = (answer, suggested[:3])

        _set_cached(key, *result)

        return result



    except Exception as e:

        logger.error(f"OpenAI error: {e}")

        return _fallback_answer(query, search_results, analysis)





def _grounded_answer(

    query: str,

    results: List[Dict[str, Any]],

    analysis: Optional[QueryAnalysis],

) -> str:

    """Deterministic answer from metadata when LLM fails."""

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

    if analysis and analysis.is_question:

        if analysis.status_hints:

            intro = f"Records matching '{', '.join(analysis.status_hints)}':\n"

    return intro + "\n".join(lines)





def _simple_answer(query: str, results: List[Dict[str, Any]]) -> str:

    return _grounded_answer(query, results, None)





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

