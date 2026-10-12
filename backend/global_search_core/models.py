"""Stable API contract for Global Search product integrations."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    filter_type: Optional[str] = "all"
    top_k: int = Field(default=5, ge=1, le=50)
    # Optional subset of configured database ids. None / empty = search all enabled.
    source_ids: Optional[list[str]] = None
    # Ignored if sent. Identity is the Authorization Bearer token only.
    user_id: Optional[str] = None
    userId: Optional[str] = None


class SearchResultItem(BaseModel):
    id: str
    title: str
    snippet: str
    content_type: str
    url: str
    metadata: Optional[dict[str, Any]] = None
    score: Optional[float] = None


class SourceStatus(BaseModel):
    name: str
    status: str
    latency_ms: int = 0
    count: int = 0
    message: Optional[str] = None


class SearchResponse(BaseModel):
    ai_answer: str = ""
    results: list[SearchResultItem] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    search_time_ms: int = 0
    total_results: int = 0
    is_question: bool = False
    # Database ids that were queried for this response.
    sources_searched: list[str] = Field(default_factory=list)
    # SPACE header: per-source health so one failure cannot empty the panel.
    partial: bool = False
    source_status: list[SourceStatus] = Field(default_factory=list)
    correlation_id: Optional[str] = None


# Loose dict shape used inside connectors before mapping to SearchResultItem.
SearchHit = dict[str, Any]
