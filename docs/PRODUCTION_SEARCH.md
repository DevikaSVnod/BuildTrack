# Production Global Search (Azure)

**Principle:** Database/API is the source of truth. Azure AI Search is a slim discovery layer. Azure OpenAI understands queries and answers over Top-K results — it never scans the database.

## Feature flags (`backend/.env`)

| Flag | Default | Meaning |
|------|---------|---------|
| `SEARCH_HYDRATE_FROM_SQL` | `true` | Hydrate search hits + project lists from SQL |
| `SEARCH_CATALOG_ENABLED` | `true` | YAML catalog drives builders + routing |
| `SEARCH_INCREMENTAL_SYNC` | `true` | Watermark sync + hash-gated embeddings |
| `SEARCH_SECURITY_TRIMMING` | `true` | OData ACL filter by project membership |
| `SEARCH_CHUNK_INDEX_FOR_DOCS` | `true` | Document clauses via blob/RAG chunks |

## Key modules

| Path | Role |
|------|------|
| `app/search/catalog/` | Schema catalog (YAML entities, loader, builder) |
| `app/search/hydrate.py` | Top-K ID → SQL authoritative records |
| `app/search/incremental_sync.py` | Watermark delta push |
| `app/search/sync_state.py` | `search_sync_state` table |
| `app/search/security_trim.py` | Query-time ACL OData |
| `app/search/document_strategy.py` | Entity index vs chunk index |
| `app/search/metrics.py` | Cost/latency counters |
| `azure/sql/004_search_staging_incremental.sql` | Staging table for SQL indexer CT |

## APIs

- `GET /api/search/catalog` — catalog + flags inventory
- `POST /api/search/sync/incremental?full=false` — delta sync
- `GET /api/search/sync/status` — watermarks / lag
- `GET /api/search/metrics` — tokens, latency, cache, sync

## Flow

User query → query intel → catalog router → Azure AI Search (Top-K IDs) → SQL hydrate → optional OpenAI answer.
