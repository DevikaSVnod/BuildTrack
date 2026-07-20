"""Stable API contract for Global Search product integrations."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    filter_type: Optional[str] = "all"
    top_k: int = Field(default=5, ge=1, le=50)


class SearchResultItem(BaseModel):
    id: str
    title: str
    snippet: str
    content_type: str
    url: str
    metadata: Optional[dict[str, Any]] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    ai_answer: str = ""
    results: list[SearchResultItem] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    search_time_ms: int = 0
    total_results: int = 0
    is_question: bool = False


# Loose dict shape used inside connectors before mapping to SearchResultItem.
SearchHit = dict[str, Any]
