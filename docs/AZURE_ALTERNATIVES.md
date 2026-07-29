# Azure Alternatives — RAG Stack Migration Options

Reference document for customer conversations about moving BuildTrack / Global Search off Azure AI Services.

**Prepared:** July 2026
**Scope:** Component-by-component alternatives for every Azure service currently in the stack.

---

## Current Azure footprint

| Component | Service in use | Configuration |
|---|---|---|
| Chat / answer generation | Azure OpenAI | `gpt-4o-mini` |
| Vision (drawing Q&A) | Azure OpenAI | Optional vision deployment (e.g. `gpt-4o`) |
| Embeddings | Azure OpenAI | `text-embedding-3-small` |
| Hybrid retrieval | Azure AI Search | `buildtrack-index`, `buildtrack-assets-index` |
| Primary database | Azure SQL Database | `buildtrack` |
| Secondary database | Azure SQL Database | `buildtrack_assets` |
| File storage | Azure Blob Storage | `buildtrack-documents` |

Everything else — Next.js, FastAPI, SQLAlchemy, JWT auth, and the Global Search pipeline
(`query → retrieve → filter → answer`) — is platform-neutral and carries over unchanged.

---

## 1. Azure OpenAI — chat models (`gpt-4o-mini`)

| Alternative | Type |
|---|---|
| OpenAI API (direct) | Same GPT models, non-Azure hosting |
| AWS Bedrock (Claude, Llama, Mistral, Amazon Nova) | Managed multi-model |
| Google Vertex AI (Gemini) | Managed |
| Anthropic Claude API | Managed LLM only |
| Cohere Command R / R+ | Managed, RAG-oriented |
| Self-hosted Llama / Mistral / Qwen (vLLM) | Open-source, self-host |

---

## 2. Azure OpenAI — embeddings (`text-embedding-3-small`)

| Alternative | Type |
|---|---|
| OpenAI embeddings (direct API) | Same family |
| Cohere Embed | Strong for search / RAG |
| Amazon Titan Embeddings (Bedrock) | AWS-native |
| Google text-embedding (Vertex) | GCP-native |
| Open-source (bge-m3, nomic-embed) | Self-host |

> **Important:** changing the embedding model requires a **full reindex** of every corpus.
> Ingestion-time and query-time embeddings must always come from the same model.

---

## 3. Azure AI Search — hybrid retrieval

| Alternative | Type | Lock-in |
|---|---|---|
| AWS Bedrock Knowledge Bases (+ OpenSearch) | Managed RAG | AWS |
| Google Vertex AI Search / Vector Search / RAG Engine | Managed RAG | GCP |
| Pinecone | Managed vector DB | Pinecone SaaS |
| Qdrant | Managed or self-host | Cloud-agnostic if self-hosted |
| Weaviate | Managed or self-host | Cloud-agnostic if self-hosted |
| Milvus / Zilliz Cloud | Large-scale vectors | Low if self-hosted |
| pgvector (Postgres) | DB-native vectors | Low |

---

## 4. Azure SQL Database

| Alternative | Type |
|---|---|
| PostgreSQL (Azure Flexible Server / AWS RDS / Cloud SQL / self-host) | Most common portable swap |
| Amazon RDS / Aurora | AWS |
| Cloud SQL | GCP |
| SQL Server (on-prem / other cloud) | Closest engine swap |

---

## 5. Azure Blob Storage

| Alternative | Type |
|---|---|
| Amazon S3 | AWS |
| Google Cloud Storage | GCP |
| MinIO | Self-host / S3-compatible |
| Any S3-compatible object store | Cloud-agnostic |

---

## 6. Full RAG stack alternatives (end-to-end)

| Option | Stack shape | Best when |
|---|---|---|
| AWS Bedrock Knowledge Bases | Managed ingest + retrieve + LLM | Customer is AWS-first |
| Google Vertex AI Search / RAG | Managed RAG + Gemini | Customer is GCP-first |
| OpenAI + Pinecone/Qdrant | BYO vector + GPT | Fastest soft exit from Azure AI |
| Claude + Qdrant/Weaviate | Strong reasoning + hybrid search | Quality + less Microsoft lock-in |
| Cohere (Embed + Rerank + Command) | RAG-specialist platform | Enterprise search + private deploy |
| Self-host: Qdrant/Weaviate + open embeddings + Llama/Mistral | Full control | Data sovereignty / air-gap |

---

## What does not change

These layers are unaffected by any of the migrations above:

- Next.js 14, React, TypeScript, Tailwind
- FastAPI, SQLAlchemy, Alembic, JWT authentication
- Global Search pipeline: `query → retrieve → filter → answer`
- Connector / extractor plugin model and multi-database fan-out

---

## Selection cheat sheet

| Customer requirement | Recommendation |
|---|---|
| Managed cloud, must leave Azure | Bedrock Knowledge Bases or Vertex AI Search |
| Least rework to this product | Qdrant or Pinecone + OpenAI or Claude |
| No vendor lock-in / self-hosted | Qdrant or Weaviate + open-source LLM |
| RAG-specialist vendor with private deployment | Cohere |
| Keep GPT model quality | OpenAI direct (still needs a search-layer replacement) |

---

## Risks to raise before committing

1. **Reindex is mandatory** whenever the embedding model changes — plan a dual-index cutover.
2. **Hybrid search parity** (keyword + vector) is essential for asset codes, drawing numbers, and document IDs. Vector-only stores are not equivalent.
3. **Document-level access control** patterns built on Azure AI Search do not port automatically.
4. **Vision / drawing analysis** must be validated early on any replacement model.
5. **Cost comparisons are workload-specific** — list prices exclude search infrastructure, egress, logging, and provisioned throughput.
6. **Avoid trading one lock-in for another** — keep embed / retrieve / generate behind interfaces in `global_search_core`.

---

## One-line summary

> Every Azure AI component has a credible peer: **Bedrock or Vertex** for managed cloud, **Qdrant / Weaviate / Pinecone** for retrieval, **OpenAI / Claude / Cohere / open models** for generation, and **PostgreSQL + S3 or MinIO** for data — while the application and search pipeline stay as they are.
