from pydantic import BaseModel
from typing import Optional, List, Any


class SearchRequest(BaseModel):
    query: str
    filter_type: Optional[str] = "all"
    top_k: int = 5


class SearchResultItem(BaseModel):
    id: str
    title: str
    snippet: str
    content_type: str
    url: str
    metadata: Optional[dict] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    ai_answer: str
    results: List[SearchResultItem]
    suggested_questions: List[str]
    search_time_ms: int
    total_results: int
    is_question: bool = False
