"""
Query understanding: detect questions, domain intent, status filters, and search terms.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

# Natural-language → Azure content_type
DOMAIN_SIGNALS: dict[str, list[str]] = {
    "handover": [
        "handover", "closeout", "close-out", "completion certificate",
        "warranty", "defects liability", "dlp", "o&m manual", "as-built",
    ],
    "drawing": [
        "drawing", "drawings", "specification", "specs", "revision", "rev ",
        "structural plan", "architectural", "discipline", "floor plan", "dwg",
    ],
    "safety": [
        "safety", "hse", "incident", "near miss", "violation", "injury",
        "observation", "hazard",
    ],
    "attendance": [
        "attendance", "present", "absent", "late arrival", "workforce on site",
        "labour", "labor register",
    ],
    "document": [
        "document control", "uploaded file", "uploaded on", "uploaded",
        "file type", "file size", "pdf", "dms", "docx", "report",
    ],
    "task": [
        "task", "site activity", "activities", "kanban", "priority task",
        "milestone",
    ],
    "project": [
        "project", "budget", "progress", "construction site",
    ],
    "team": [
        "team member", "team members", "core members", "core team",
        "workforce", "personnel", "staff", "members of", "member in",
        "project manager", "site engineer", "contractor", "engineers",
        "who is", "who are", "who work",
    ],
}

STATUS_WORDS = {
    "pending": ["pending", "not signed", "awaiting", "outstanding"],
    "approved": ["approved", "signed off"],
    "open": ["open", "unresolved", "active incident"],
    "closed": ["closed", "resolved", "completed"],
    "high": ["high priority", "high severity", "urgent"],
}

QUESTION_STARTERS = (
    "what", "which", "who", "where", "when", "how", "why",
    "show", "list", "find", "tell", "give", "are there", "is there",
    "do we", "does", "can you", "any",
)

STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "me", "my", "our", "we", "you", "your", "all", "any", "some", "with",
    "from", "about", "into", "that", "this", "these", "those", "there",
    "their", "them", "it", "its", "by", "as", "up", "out", "so", "if",
    "not", "no", "yes", "please", "tell", "show", "list", "find", "give",
    "what", "which", "who", "where", "when", "how", "why", "many", "much",
    "status", "documents", "document", "items", "records",
}


@dataclass
class QueryAnalysis:
    original: str
    is_question: bool
    search_text: str
    content_types: List[str] = field(default_factory=list)
    status_hints: List[str] = field(default_factory=list)
    top_k: int = 8

    def cache_suffix(self) -> str:
        parts = [self.search_text]
        if self.content_types:
            parts.append("|".join(sorted(self.content_types)))
        if self.status_hints:
            parts.append("|".join(sorted(self.status_hints)))
        return "|".join(parts)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def is_question(query: str) -> bool:
    q = _normalize(query)
    if not q:
        return False
    if q.endswith("?"):
        return True
    if any(q.startswith(s + " ") or q == s for s in QUESTION_STARTERS):
        return True
    if re.search(r"\b(how many|how much|number of|no\.?\s*of|what is|what are|which)\b", q):
        return True
    return False


def is_workforce_aggregate_query(query: str) -> bool:
    """Matches /team page — total personnel, not daily attendance."""
    q = _normalize(query)
    if re.search(r"\b(total|all|entire|full)\s+(workforce|personnel|staff|team)\b", q):
        return True
    if re.search(r"\bworkforce\s+(total|count|size|number)\b", q):
        return True
    if q in ("total workforce", "total personnel", "all personnel", "all workforce"):
        return True
    if "personnel registered" in q or "how many personnel" in q or "how many workforce" in q:
        return True
    return False


def detect_content_types(query: str) -> List[str]:
    q = _normalize(query)
    if is_workforce_aggregate_query(q):
        return ["team"]
    found: List[str] = []
    for ctype, signals in DOMAIN_SIGNALS.items():
        if any(sig in q for sig in signals):
            found.append(ctype)
    # "workforce" alone → team (LMS), not attendance register
    if "workforce" in q and "attendance" not in q and "present" not in q and "absent" not in q:
        if "team" not in found:
            found.append("team")
        found = [t for t in found if t != "attendance"]
    return found


def detect_status_hints(query: str) -> List[str]:
    q = _normalize(query)
    hints: List[str] = []
    for status, phrases in STATUS_WORDS.items():
        if any(p in q for p in phrases):
            hints.append(status)
    return hints


def parse_progress_filter(query: str) -> Optional[int]:
    """
    Extract a numeric progress value from filter-style queries.
    e.g. 'projects with 0 progress', 'progress at 100%', 'zero progress'
    """
    q = _normalize(query)
    if re.search(r"\b(zero|no)\s+progress\b", q):
        return 0
    patterns = [
        r"(?:with|at|having|equals?|=)\s*(\d+)\s*(?:%|\s)?progress",
        r"progress\s*(?:of|at|is|=)\s*(\d+)\s*%?",
        r"(\d+)\s*%\s*progress",
        r"progress\s*(\d+)\s*%",
    ]
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            return int(m.group(1))
    return None


# Natural-language status → metadata.status values in the index
_STATUS_FILTER_MAP = {
    "on hold": "On Hold",
    "in progress": "In Progress",
    "planning": "Planning",
    "completed": "Completed",
    "done": "Done",
    "open": "Open",
    "closed": "Closed",
    "resolved": "Resolved",
    "todo": "To Do",
    "to do": "To Do",
    "review": "Review",
    "approved": "Approved",
    "pending": "Pending",
}


def parse_status_filter(query: str) -> Optional[str]:
    """Extract an exact status filter when the query asks for it."""
    q = _normalize(query)
    # Longest phrase first so "in progress" beats "progress"
    for phrase in sorted(_STATUS_FILTER_MAP.keys(), key=len, reverse=True):
        if phrase in q:
            return _STATUS_FILTER_MAP[phrase]
    return None


def target_content_types_for_filter(query: str, analysis: QueryAnalysis) -> List[str]:
    """Which content types to scan for structured metadata filters."""
    q = _normalize(query)
    if any(w in q for w in ("timeline", "phase", "phases", "milestone", "gantt")):
        return ["timeline"]
    if "task" in q or "activit" in q:
        return ["task"]
    if "project" in q:
        # Project-level progress queries also include timeline phases (0% phases).
        if parse_progress_filter(query) is not None:
            return ["project", "timeline"]
        return ["project"]
    if analysis.content_types:
        return list(dict.fromkeys(analysis.content_types))
    return ["project", "task", "timeline", "document", "handover", "drawing", "safety"]


def extract_search_terms(query: str) -> str:
    """Strip question filler; keep entities and domain terms for BM25."""
    q = _normalize(query).rstrip("?")
    tokens = re.findall(r"[a-z0-9]+", q)
    kept: List[str] = []
    for t in tokens:
        if t in STOP_WORDS and len(tokens) > 3:
            continue
        kept.append(t)
    if not kept:
        return query.strip()
    # Re-inject multi-word domain phrases if present in original
    text = " ".join(kept)
    for signals in DOMAIN_SIGNALS.values():
        for sig in signals:
            if " " in sig and sig in q:
                text = f"{text} {sig}"
    return text.strip() or query.strip()


def analyze_query(query: str, default_top_k: int = 8) -> QueryAnalysis:
    q = query.strip()
    question = is_question(q)
    content_types = detect_content_types(q)
    status_hints = detect_status_hints(q)

    # Questions: use full query for semantic; lean keywords for BM25 merge
    search_text = q if question else extract_search_terms(q)
    if question and content_types:
        # Add domain anchor so BM25 doesn't drift to unrelated "pending" projects
        search_text = f"{' '.join(content_types)} {extract_search_terms(q)}"

    top_k = 10 if question else default_top_k
    if is_workforce_aggregate_query(_normalize(q)):
        top_k = 15
    elif "team" in content_types:
        # Workforce / member queries need enough results to surface all project members
        top_k = 15
    elif content_types and not question:
        top_k = max(top_k, 8)

    if is_upload_date_query(q):
        if "document" not in content_types:
            content_types = ["document", *content_types]
        top_k = max(top_k, 10)

    if is_file_detail_query(q):
        if "document" not in content_types:
            content_types = ["document", *content_types]
        top_k = max(top_k, 12)

    if is_document_content_query(q):
        if "document" not in content_types:
            content_types = ["document", *content_types]
        top_k = max(top_k, 12)

    # Filter queries (progress/status) must return every match, not top-K relevance picks.
    if parse_progress_filter(q) is not None or parse_status_filter(q) is not None:
        top_k = 50

    return QueryAnalysis(
        original=q,
        is_question=question,
        search_text=search_text,
        content_types=content_types,
        status_hints=status_hints,
        top_k=top_k,
    )


def extract_upload_date(query: str) -> Optional[str]:
    """
    Parse an upload date from natural language.
    Returns ISO date YYYY-MM-DD or None.
    Handles: 2026-06-01, June 1 2026, Jun1 2026, Jun 1st 2026
    """
    q = query.strip()

    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", q)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    month_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    month_pattern = "|".join(sorted(month_map.keys(), key=len, reverse=True))

    # June 1 2026 / Jun 1, 2026 / Jun1 2026
    m = re.search(
        rf"\b({month_pattern})\.?\s*(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(20\d{{2}})\b",
        q,
        re.IGNORECASE,
    )
    if m:
        month_key = m.group(1).lower().rstrip(".")
        month = month_map.get(month_key)
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"

    # 1 June 2026
    m = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_pattern})\.?\s+(20\d{{2}})\b",
        q,
        re.IGNORECASE,
    )
    if m:
        month_key = m.group(2).lower().rstrip(".")
        month = month_map.get(month_key)
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"

    return None


def is_upload_date_query(query: str) -> bool:
    q = _normalize(query)
    if extract_upload_date(query):
        return True
    return bool(re.search(r"\bupload(?:ed)?\s+(?:on|date)\b", q))


def is_file_detail_query(query: str) -> bool:
    q = _normalize(query)
    return bool(
        re.search(
            r"\b(file size|file type|how (?:big|large)|size of|bytes|kb|mb|megabytes|kilobytes)\b",
            q,
        )
    )


DRAWING_NO_PATTERN = re.compile(r"\b([A-Z]{2}-\d{3}-[A-Z0-9])\b", re.IGNORECASE)


def extract_drawing_no(query: str) -> Optional[str]:
    m = DRAWING_NO_PATTERN.search(query)
    return m.group(1).upper() if m else None


_CONTEXTUAL_LAYOUT = re.compile(
    r"\b(floor\s*plan|apartment|kitchen|bedroom|bathroom|living\s*room|dining|"
    r"corridor|entrance|entry|exit|balcony|wardrobe|study|layout|room|ensuite|"
    r"door|doors|window|access|circulation|foyer|lobby|stair|stairs|zone|zones|"
    r"furniture|furnishing|fixture|fixtures|facilities|restroom|washroom|lavatory|wc|"
    r"desk|chair|bed|sofa|couch|table|toilet|sink|shower|workstation|how\s+many|number\s+of|count|points?)\b",
    re.I,
)


def is_drawing_contextual_layout_query(query: str) -> bool:
    """Floor-plan / layout questions — answer from extracted text, not vision fallback."""
    if not is_drawing_content_query(query):
        return False
    return bool(_CONTEXTUAL_LAYOUT.search(_normalize(query)))


_COUNT_QUERY = re.compile(
    r"\b(how\s+many|number\s+of|no\.?\s*of|count|total)\b.{0,40}\b("
    r"chairs?|desks?|doors?|tables?|workstations?|beds?|sofas?|fixtures?|rooms?|"
    r"entries|exits|entry|exit|points?)\b|"
    r"\b(chairs?|desks?|doors?|tables?|workstations?|beds?|sofas?|fixtures?|rooms?|"
    r"entries|exits|entry|exit|points?)\b.{0,40}\b(how\s+many|number\s+of|no\.?\s*of|count)\b",
    re.I,
)


def is_drawing_count_query(query: str) -> bool:
    """Counting questions on floor plans / images (chairs, doors, rooms, etc.)."""
    q = _normalize(query)
    if not _COUNT_QUERY.search(q):
        return False
    if is_drawing_content_query(query):
        return True
    if is_drawing_object_query(query):
        return True
    return bool(
        re.search(
            r"\b(floor\s*plan|drawing|layout|blueprint|unit|apartment|bedroom|"
            r"image|photo|picture|hall|room|conference|site\s*plan|grading\s*plan|campus)\b",
            q,
        )
    )


_LAYOUT_IDENT = re.compile(
    r"\b(what\s+type\s+of\s+room|what\s+kind\s+of\s+room|what\s+does\s+this\s+layout\s+represent|"
    r"what\s+is\s+this\s+(room|layout|space)|identify\s+the\s+room|room\s+type|"
    r"what\s+space|layout\s+represent|represent\s+this\s+layout)\b",
    re.I,
)

_FURNITURE_INVENTORY = re.compile(
    r"\b(furniture|furnishing|furnishings|fixtures?|facilities|what\s+is\s+(?:inside|in)\s+the|"
    r"what\s+(?:furniture|fixtures|facilities)|list\s+(?:the\s+)?(?:furniture|items|fixtures|facilities)|"
    r"available\s+inside|inside\s+the\s+(?:room|restroom|washroom|bathroom|area)|"
    r"items\s+in\s+the\s+room|contains?\s+(?:office\s+)?(?:furniture|fixtures|workstations?))\b",
    re.I,
)

_SITE_INVENTORY = re.compile(
    r"\b(buildings?|structures?|blocks?|hostels?|roads?|utilities?|campus|site\s+features?|"
    r"grading\s+control|gcp|legend|what\s+(?:is|are)\s+on\s+(?:this\s+)?site|"
    r"list\s+(?:the\s+)?(?:buildings?|structures?|roads?|site\s+features?)|"
    r"what\s+(?:buildings?|roads?|facilities?)\s+(?:are|is)\s+(?:on|shown|visible))\b",
    re.I,
)

_OBJECT_QUERY = re.compile(
    r"\b(what\s+(?:all\s+)?objects?|objects?\s+(?:are\s+)?(?:there\s+)?in|"
    r"what\s+(?:can\s+you\s+)?see\s+in\s+(?:the\s+)?(?:image|photo|picture|drawing)|"
    r"identify\s+(?:the\s+)?objects?|list\s+(?:the\s+)?objects?|"
    r"objects?\s+in\s+(?:this\s+|the\s+)?(?:image|photo|picture|drawing)|"
    r"what\s+is\s+in\s+(?:this\s+|the\s+)?(?:image|photo|picture))\b",
    re.I,
)


def is_drawing_object_query(query: str) -> bool:
    """Questions about objects visible in an uploaded image/drawing."""
    q = _normalize(query)
    if not _OBJECT_QUERY.search(q):
        return False
    # Treat as drawing/image content even without explicit "drawing" keyword
    # when the user clearly asks about image objects.
    return True


def is_which_drawing_query(query: str) -> bool:
    """User asks which drawing(s) match a description — answer must name the sheet."""
    q = _normalize(query)
    if re.search(r"\b(which|what)\s+drawing\b", q):
        return True
    return bool(
        re.search(r"\bdrawing\b", q)
        and re.search(r"\b(which|what)\b", q)
        and re.search(r"\b(contains?|shows?|has|includes?|with)\b", q)
    )

_ZONE_FACILITIES = re.compile(
    r"\b(restroom|washroom|bathroom|toilet\s+area|lavatory|wc|ensuite|shower\s+room)\b",
    re.I,
)


def is_drawing_zone_facilities_query(query: str) -> bool:
    """List fixtures/facilities in a named zone (restroom, bathroom, etc.)."""
    if not is_drawing_content_query(query):
        return False
    q = _normalize(query)
    return bool(_ZONE_FACILITIES.search(q)) and bool(
        re.search(r"\b(facilities?|fixtures?|available|inside|what)\b", q)
    )


def is_drawing_furniture_inventory_query(query: str) -> bool:
    """List furniture/fixtures/objects visible on a floor plan or image."""
    if is_drawing_object_query(query):
        return True
    if not is_drawing_content_query(query):
        return False
    return bool(_FURNITURE_INVENTORY.search(_normalize(query)))


def is_drawing_site_inventory_query(query: str) -> bool:
    """List buildings, roads, utilities, or site features on a civil/site plan."""
    if not is_drawing_content_query(query):
        return False
    q = _normalize(query)
    if _SITE_INVENTORY.search(q):
        return True
    return bool(
        re.search(r"\b(site\s+plan|grading\s+plan|campus\s+plan|master\s+plan)\b", q)
        and re.search(r"\b(what|list|show|name|identify)\b", q)
    )


def is_drawing_layout_identification_query(query: str) -> bool:
    """Questions asking what room/space type a floor plan shows."""
    if not is_drawing_content_query(query):
        return False
    return bool(_LAYOUT_IDENT.search(_normalize(query)))


def is_drawing_vision_first_query(query: str) -> bool:
    """Layout questions that must read the image — title/metadata may be wrong."""
    return (
        is_drawing_count_query(query)
        or is_drawing_layout_identification_query(query)
        or is_drawing_furniture_inventory_query(query)
        or is_drawing_site_inventory_query(query)
        or is_drawing_zone_facilities_query(query)
        or is_drawing_object_query(query)
        or is_drawing_contextual_layout_query(query)
    )


def is_drawing_fact_query(query: str) -> bool:
    """Factual values from drawing extracted text — use text path, not vision."""
    if not is_drawing_content_query(query):
        return False
    q = _normalize(query)
    return bool(
        re.search(r"\b(pile|diameter|piling)\b", q)
        or re.search(r"\b(span|truss)\b", q)
        or re.search(r"\b(incomer|rating)\b", q)
        or is_drawing_contextual_layout_query(query)
    )


def is_drawing_text_first_query(query: str) -> bool:
    """Drawing questions that must use extracted sheet text (never vision-only fallback)."""
    return is_drawing_fact_query(query) or is_drawing_contextual_layout_query(query)


def is_drawing_content_query(query: str) -> bool:
    """Question about technical content inside an engineering drawing file."""
    q = _normalize(query).rstrip("?")
    if is_file_detail_query(query):
        return False
    if is_drawing_object_query(query):
        return True
    from app.search.drawing_sheet_intel import is_sheet_intel_query

    if is_sheet_intel_query(query):
        return True
    if _COUNT_QUERY.search(q) and re.search(
        r"\b(image|photo|picture|hall|conference|room|chairs?|tables?)\b", q
    ):
        return True
    drawing_no = extract_drawing_no(query)
    if drawing_no:
        if re.search(
            r"\b(pile|piling|diameter|dimension|layout|spacing|length|depth|revision|"
            r"note|notes|spec|grid|foundation|location|position|where|associated|set\s+out|"
            r"setting\s+out|sufficient|support|evidence|floor\s*plan|kitchen|bedroom|"
            r"bathroom|living|dining|corridor|balcony|apartment|room|entry|exit|door|"
            r"access|how\s+many|visible|what|which|how|find|on|in|from|scale|isometric|"
            r"perspective|section|elevation|weight|units?|2d|3d|view)\b",
            q,
        ):
            return True
        if query.strip().endswith("?"):
            return True
    if re.search(r"\bon\s+(?:drawing|sheet)\b", q):
        return True
    if re.search(r"\bdrawing\s+(?:no|number|#)\b", q):
        return True
    if re.search(r"\b(floor\s*plan|layout|blueprint)\b", q) and re.search(
        r"\b(beds?|chairs?|doors?|rooms?|furniture|fixtures?|how\s+many|number\s+of|count)\b",
        q,
    ):
        return True
    if _COUNT_QUERY.search(q) and re.search(
        r"\b(floor\s*plan|drawing|layout|unit|apartment|residential)\b", q
    ):
        return True
    if re.search(r"\bdrawing\b", q) and re.search(
        r"\b(find|show|which|locate|that shows|with a|residential|apartment|"
        r"floor\s*plan|layout|studio|bedroom)\b",
        q,
    ):
        return True
    return False


def is_document_content_query(query: str) -> bool:
    """Question about text inside an uploaded file (not metadata like size/uploader)."""
    q = _normalize(query).rstrip("?")
    if is_file_detail_query(query):
        return False
    if is_drawing_content_query(query):
        return True
    content_signals = re.search(
        r"\b(mention|mentioned|say|says|state|states|describe|detail|details|content|"
        r"conclusion|conclusions|recommendation|recommendations|section|paragraph|"
        r"what|which|how many|how much|list|summarize|summary|explain|find|inside|within|"
        r"who|when|where|why|issues?|findings?|equipment|inspected|inspector)\b",
        q,
    )
    file_signals = re.search(
        r"\b(report|document|pdf|docx|xlsx|file|manual|specification|specs|attachment|"
        r"drawing|sheet|plan|inspection|handover)\b",
        q,
    )
    if file_signals and (content_signals or query.strip().endswith("?")):
        return True
    # Facts usually live inside uploaded PDFs/DOCX even when the user omits "document"
    if re.search(r"\b(who|what|when|which|how many|how much|where|why)\b", q) and re.search(
        r"\b(inspect(ed|or|ion)?|inspector|equipment|machinery|crane|milestone|risk|finding|findings|"
        r"leed|elevator|parking|site plan|bridge|tower|hse|materials?|concrete|steel|asphalt|"
        r"ev charging|meeting rooms?|floor plate|budget spent|work package|tenant|"
        r"issues?|progress|schedule|safety measures?|ppe|scope|cost|budget)\b",
        q,
    ):
        return True
    if content_signals and re.search(
        r"\b(bridge|highway|tower|metro|commercial tower|project)\b", q
    ):
        return True
    if query.strip().endswith("?") and re.search(
        r"\b(bridge|highway|tower|metro|inspection|handover|budget|safety|equipment)\b", q
    ):
        return True
    return bool(
        re.search(r"\bproject\s+report\b", q)
        or re.search(r"\b(in|from|inside|within)\s+(the\s+)?[\w\s-]+\s+(report|document|file)\b", q)
    )


def is_file_content_query(query: str) -> bool:
    return is_document_content_query(query)


def score_drawing_match(query: str, title: str, metadata: Optional[dict] = None) -> float:
    """Boost drawings whose number/title matches the question."""
    score = 0.0
    drawing_no = extract_drawing_no(query)
    meta = metadata or {}
    title_l = title.lower()
    qn = _normalize(query)
    if drawing_no:
        if drawing_no.lower() in title_l:
            score += 60.0
        if str(meta.get("drawing_no", "")).upper() == drawing_no:
            score += 70.0
    for tok in re.findall(r"[a-z0-9]+", qn):
        if len(tok) > 3 and tok in title_l:
            score += 4.0
    # Phrase match: "residential unit floor plan" → ST-009-B title
    if re.search(r"\bresidential\b", qn) and "residential" in title_l:
        score += 12.0
    if re.search(r"\bapartment\b", qn) and ("apartment" in title_l or "unit" in title_l):
        score += 14.0
    if re.search(r"\bstudio\b", qn) and "studio" in title_l:
        score += 14.0
    if re.search(r"\bfloor\s*plan\b", qn) and "floor plan" in title_l:
        score += 10.0
    if re.search(r"\bmaster\s*plan\b", qn) and "master plan" in title_l:
        score += 12.0
    if re.search(r"\bconveyor\b", qn) and "conveyor" in title_l:
        score += 16.0
    if re.search(r"\boffice\b", qn) and ("office" in title_l or "workstation" in title_l):
        score += 20.0
    if re.search(r"\bfurniture\b", qn) and (
        "workstation" in title_l or "office" in title_l or "furniture" in title_l
    ):
        score += 14.0
    if re.search(r"\bworkstation\b", qn) and "workstation" in title_l:
        score += 18.0
    if re.search(r"\bconference\b", qn) and "conference" in title_l:
        score += 14.0
    # Penalise obvious mismatches for descriptive find queries
    if re.search(r"\b(apartment|residential|studio|bedroom)\b", qn):
        if re.search(r"\b(conveyor|master\s*plan|screw|site\s*plan)\b", title_l):
            score -= 25.0
    if re.search(r"\b(office|workstation|furniture|conference)\b", qn):
        if re.search(r"\b(residential|apartment|studio|bedroom|site\s*master)\b", title_l):
            score -= 22.0
        if "master plan" in title_l and "office" not in title_l:
            score -= 18.0
    return score


def extract_document_name_tokens(query: str) -> List[str]:
    """Tokens from the document name phrase, e.g. after 'of' in a file-size question."""
    q = _normalize(query).rstrip("?")
    m = re.search(r"\bin\s+(?:the\s+)?(.+?)\s+(?:report|document|file|pdf|docx)\b", q)
    if m:
        phrase = m.group(1).strip()
    else:
        m = re.search(r"\bin\s+(?:the\s+)?(.+?)$", q)
        if m:
            phrase = m.group(1).strip()
        else:
            m = re.search(r"\b(?:of|for|named|called)\s+(.+)$", q)
            phrase = m.group(1) if m else q
    return [
        t for t in re.findall(r"[a-z0-9]+", phrase)
        if len(t) > 3 and t not in STOP_WORDS and t not in {"size", "file", "document", "report", "measure", "measures", "safety", "mentioned"}
    ]


def is_safety_measures_query(query: str) -> bool:
    q = _normalize(query)
    return bool(re.search(r"\bsafety\s+measures?\b|\bmeasures?\s+.*\bsafety\b|\bwhat\s+safety\b", q))


def is_inspector_query(query: str) -> bool:
    q = _normalize(query)
    return bool(
        re.search(
            r"\bwho\s+inspect(?:ed|ion)?\b|\bwhich\s+inspector\b|\binspector(?:\s+name)?\b",
            q,
        )
    )


def is_handover_workflow_query(query: str) -> bool:
    """User wants actions / next steps for handover closeout — not a document list."""
    q = _normalize(query)
    handover = re.search(
        r"\bhandover|closeout|close-out|completion certificate|"
        r"defects liability|dlp|o&?m manual|as-built",
        q,
    )
    procedural = re.search(
        r"\bnext step|what (?:are|is) the next|what should|what do we|"
        r"how to proceed|who is responsible|who should|timeline for|"
        r"action(?:s)? required|what happens next|workflow|process for|"
        r"still pending|pending handover",
        q,
    )
    return bool(handover and procedural)


def score_document_title_match(query: str, title: str) -> float:
    """Boost documents whose filename matches the report named in the question."""
    q = _normalize(query).rstrip("?")
    t = title.replace("_", " ").lower()
    score = 0.0

    m = re.search(r"\bin\s+(?:the\s+)?(.+?)$", q)
    phrase = m.group(1).strip() if m else q
    phrase_norm = phrase.replace("_", " ")

    if "project report" in phrase_norm:
        if "project report" in t or "project_report" in title.lower():
            score += 55.0
        if "budget" in t and "project report" not in t:
            score -= 45.0
    if "budget report" in phrase_norm and "budget" in t:
        score += 25.0

    for tok in extract_document_name_tokens(query):
        if tok in t:
            score += 10.0
    return score


def extract_project_qualifier(query: str) -> Optional[str]:
    """
    Extract a specific project name from the query.
    Looks for multi-word capitalized phrases or phrases after 'in/for/of/on/at'.
    E.g. "Workforce in Highway Bridge Expansion" → "highway bridge expansion"
    E.g. "Core Members in Metro Station Renovation Project" → "metro station renovation"
    """
    q = query.strip()
    # Single generic words at the END that are part of the query, not the project name.
    # Only strip one-word suffixes (e.g. "Project", "Site") — never compound nouns
    # that are part of the actual project name (e.g. "Renovation", "Expansion").
    _TRAILING_NOISE = re.compile(
        r"\s+(?:project|construction site|work site|team|core|members?|staff"
        r"|personnel|managers?|engineers?|contractors?)\s*$",
        re.IGNORECASE,
    )
    # Match phrases after prepositions: "in/for/of/on/at <Name...>"
    m = re.search(
        r"\b(?:in|for|of|on|at|under|from)\s+([A-Z][A-Za-z0-9\s\-]+?)(?:\s*$|\s*[,?])",
        q,
    )
    if m:
        phrase = m.group(1).strip()
        # Strip trailing noise words (e.g. "Project", "Site", "Team")
        phrase = _TRAILING_NOISE.sub("", phrase).strip()
        if len(phrase.split()) >= 2:  # at least 2 words = likely a project name
            return phrase.lower()
    return None


def rerank_score(item: dict, analysis: QueryAnalysis) -> float:
    """Boost results that match detected intent (on top of Azure score)."""
    base = float(item.get("score") or 0)
    title = (item.get("title") or "").lower()
    snippet = (item.get("snippet") or "").lower()
    content = (item.get("content") or snippet)[:400].lower()
    ctype = item.get("content_type") or ""
    meta = item.get("metadata") or {}
    meta_text = " ".join(str(v).lower() for v in meta.values() if v)

    boost = 0.0

    if is_workforce_aggregate_query(analysis.original):
        if ctype == "team":
            boost += 20.0
        else:
            boost -= 25.0
    elif analysis.content_types:
        if ctype in analysis.content_types:
            boost += 12.0
        else:
            boost -= 10.0

    for hint in analysis.status_hints:
        if hint in title or hint in snippet or hint in meta_text:
            boost += 5.0
        status_val = str(meta.get("status", "")).lower()
        if hint in status_val:
            boost += 6.0

    # ── Project qualifier check ────────────────────────────────────────────────
    # If the query names a specific project (e.g. "Highway Bridge Expansion"),
    # strongly boost results that contain it and penalize those that don't.
    project_qualifier = extract_project_qualifier(analysis.original)
    if project_qualifier:
        qualifier_words = set(project_qualifier.split())
        # How many qualifier words appear in this result's text?
        result_text = f"{title} {snippet} {content} {meta_text}"
        matches = sum(1 for w in qualifier_words if w in result_text and len(w) > 3)
        match_ratio = matches / len(qualifier_words) if qualifier_words else 0

        if match_ratio >= 0.6:
            boost += 10.0   # most qualifier words found → strong boost
        elif match_ratio >= 0.3:
            boost += 3.0    # partial match
        elif ctype == "team":
            # For workforce queries: mild penalty only — don't hide members whose
            # docs weren't re-indexed yet with the project name
            boost -= 3.0
        else:
            boost -= 12.0   # non-team result doesn't mention the project → penalize hard

    # Title / phrase overlap with original question
    orig_tokens = set(re.findall(r"[a-z0-9]+", analysis.original.lower()))
    overlap = sum(1 for t in orig_tokens if t in title or t in snippet and len(t) > 3)
    boost += min(overlap * 0.8, 4.0)

    # Upload-date queries: boost the doc uploaded on that exact date
    target_date = extract_upload_date(analysis.original)
    if target_date and ctype == "document":
        item_date = str(meta.get("upload_date", ""))
        item_display = str(meta.get("upload_date_display", "")).lower()
        if item_date == target_date:
            boost += 30.0
        elif target_date in content or target_date.replace("-", " ") in content:
            boost += 20.0
        elif item_display and any(
            part in item_display
            for part in target_date.split("-")[1:]  # month/day fragments
        ):
            boost += 8.0
        elif item_date and item_date != target_date:
            boost -= 12.0

    # File-size / document detail queries: prefer the named document over project/timeline rows
    if is_file_detail_query(analysis.original):
        doc_tokens = extract_document_name_tokens(analysis.original)
        if ctype == "document":
            boost += 18.0
            if doc_tokens:
                title_hits = sum(1 for t in doc_tokens if t in title.replace("_", " "))
                snippet_hits = sum(1 for t in doc_tokens if t in snippet.replace("_", " "))
                boost += min(title_hits * 6.0 + snippet_hits * 2.0, 24.0)
            if meta.get("file_size") or meta.get("file_size_display"):
                boost += 8.0
        elif ctype in {"project", "timeline", "handover", "report", "safety", "task"}:
            boost -= 15.0

    # Text extracted from blob files (RAG index) — boost for content questions
    if meta.get("content_source") in (
        "blob_rag",
        "drawing_sheet_notes",
        "document_body_text",
    ) or meta.get("source") in (
        "blob_rag",
        "drawing_sheet_notes",
        "document_body_text",
    ):
        if analysis.is_question:
            boost += 20.0
        if len(snippet) > 100 and "uploaded by" not in snippet[:90]:
            boost += 10.0

    if is_document_content_query(analysis.original):
        if ctype == "document":
            boost += 28.0
            boost += score_document_title_match(analysis.original, item.get("title", ""))
            doc_tokens = extract_document_name_tokens(analysis.original)
            if doc_tokens:
                title_hits = sum(1 for t in doc_tokens if t in title.replace("_", " "))
                snippet_hits = sum(1 for t in doc_tokens if t in snippet.replace("_", " "))
                boost += min(title_hits * 8.0 + snippet_hits * 4.0, 32.0)
            # Prefer real uploaded file content over seed/sync placeholders
            if "buildtrack document id" in snippet:
                boost -= 40.0
            if meta.get("content_source") in ("blob_rag", "document_body_text") and "buildtrack document id" not in snippet:
                boost += 30.0
            if meta.get("body_text") and len(str(meta.get("body_text") or "")) > 80:
                boost += 12.0
            if meta.get("file_type", "").upper() == "DOCX" and "project report" in analysis.original.lower():
                boost += 15.0
        elif ctype == "drawing" and is_drawing_content_query(analysis.original):
            boost += 35.0
            boost += score_drawing_match(analysis.original, item.get("title", ""), meta)
            if meta.get("content_source") in ("blob_rag", "drawing_sheet_notes"):
                boost += 35.0
            if extract_drawing_no(analysis.original):
                boost += 20.0
        elif ctype in {"project", "safety", "task", "timeline", "handover", "report"}:
            boost -= 22.0

    if is_drawing_content_query(analysis.original):
        if ctype == "drawing":
            boost += 40.0
            boost += score_drawing_match(analysis.original, item.get("title", ""), meta)
            if meta.get("content_source") in ("blob_rag", "drawing_sheet_notes"):
                boost += 40.0
        elif ctype == "document" and extract_drawing_no(analysis.original):
            boost -= 15.0
        elif ctype in {"project", "safety", "task", "timeline", "handover", "report"}:
            boost -= 25.0

    return base + boost
