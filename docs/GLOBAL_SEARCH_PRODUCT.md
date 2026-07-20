# Global Search Product

Package the POC as **Search API + UI widget + plugins** so other projects integrate without forking BuildTrack code.

## Architecture

```
┌──────────────────────────────────────┐
│  UI widget (frontend/lib/global-search) │
│  createSearchClient + host config    │
└─────────────────┬────────────────────┘
                  │ POST /api/search/*
┌─────────────────▼────────────────────┐
│  SearchPipeline (global_search_core) │
│  query → retrieve → filter → answer  │
└─────────────────┬────────────────────┘
                  │ connector plugin
┌─────────────────▼────────────────────┐
│  BuildTrackConnector (reference)     │
│  Azure Search + SQL enrich + workforce│
└─────────────────┬────────────────────┘
                  │ extractor plugins (index time)
┌─────────────────▼────────────────────┐
│  drawing_intelligence, document_body │
└──────────────────────────────────────┘
```

## Backend layout

| Path | Role |
|------|------|
| `backend/global_search_core/` | **Product SDK** — models, pipeline, registry, interfaces |
| `backend/app/connectors/` | Host-specific **connector plugins** |
| `backend/app/extractors/` | Host-specific **extractor plugins** |
| `backend/app/plugins/` | Registers plugins at startup |
| `backend/app/search/pipeline_factory.py` | Wires pipeline + BuildTrack intel helpers |

BuildTrack remains the **reference implementation**. New customers add their own connector/extractor under `app/connectors/` and `app/extractors/`.

## API contract (stable)

### `POST /api/search/results`
Fast hybrid search — results only.

### `POST /api/search/answer`
AI answer (uses result cache when available).

### `POST /api/search/`
Combined search + answer (legacy).

### `GET /api/search/plugins`
Lists registered connectors and extractors.

**Request body:**
```json
{
  "query": "How many chairs in CI-003-C?",
  "filter_type": "all",
  "top_k": 10
}
```

**Response:**
```json
{
  "ai_answer": "...",
  "results": [{ "id", "title", "snippet", "content_type", "url", "metadata", "score" }],
  "suggested_questions": [],
  "search_time_ms": 400,
  "total_results": 3,
  "is_question": true
}
```

Models live in `global_search_core/models.py` (single source of truth).

## Add a new customer connector

1. Create `app/connectors/acme.py`:

```python
from global_search_core.connector import SearchConnector, SearchContext

class AcmeConnector(SearchConnector):
    name = "acme"

    def retrieve(self, *, context, query, filter_type, top_k, analysis):
        # Call Acme's search index / API
        return hits  # list of dicts matching SearchHit shape
```

2. Register in `app/plugins/__init__.py`:

```python
from app.connectors.acme import AcmeConnector
register_connector(AcmeConnector())
set_default_connector("acme")  # or multi-tenant routing later
```

3. Implement `context` in routes — pass `db`, `tenant_id`, etc.

## Add a new extractor (optional intelligence)

1. Create `app/extractors/acme.py` implementing `ContentExtractor`.
2. Register with `register_extractor(...)`.
3. Call from your upload/index path:

```python
from global_search_core.registry import get_extractors_for

for ext in get_extractors_for("document"):
    result = ext.extract(ExtractionInput(...))
    # persist result.text / result.structured
```

## Frontend integration

1. Copy `frontend/lib/global-search/` into the host app (future: publish as `@yourco/global-search`).
2. Create host config (see `buildtrack.config.ts`):

```typescript
export const acmeSearchConfig: GlobalSearchConfig = {
  apiBaseUrl: "https://api.acme.com/api",
  getAuthToken: () => localStorage.getItem("token"),
  contentTypes: { document: { id: "document", label: "Doc", ... } },
  onOpenResult: (item) => router.push(item.url),
};
```

3. Use the client:

```typescript
import { createSearchClient } from "@/lib/global-search";

const search = createSearchClient({
  apiBaseUrl: acmeSearchConfig.apiBaseUrl,
  getAuthToken: acmeSearchConfig.getAuthToken,
});

const results = await search.searchResults({ query: "safety report", top_k: 8 });
```

4. Embed `SearchBar` (BuildTrack) or build a thin wrapper that reads from `GlobalSearchConfig`.

## Roadmap to standalone product

| Phase | Deliverable |
|-------|-------------|
| **Now (v0.1)** | `global_search_core` package + plugin registry + BuildTrack reference |
| **v0.2** | Publish `pip install global-search-core`, extract npm widget |
| **v0.3** | Hosted SaaS option (API key + tenant) |
| **v0.4** | Connector marketplace / config-only onboarding |

## Verify locally

```bash
cd backend
py -3.10 -c "from app.plugins import register_all_plugins; register_all_plugins(); from global_search_core.registry import list_connectors; print(list_connectors())"
# → ['buildtrack']

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/search/plugins
```

BuildTrack behavior is unchanged — search routes now delegate to `SearchPipeline` with the registered connector.
