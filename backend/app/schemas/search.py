from pydantic import BaseModel
from typing import Optional, List, Any

# Re-export stable product contract (single source of truth in global_search_core).
from global_search_core.models import (  # noqa: F401
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
