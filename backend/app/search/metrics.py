"""In-process search/index cost and latency metrics for production observability."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional


@dataclass
class _Counters:
    search_queries: int = 0
    search_latency_ms_total: float = 0.0
    hydrate_calls: int = 0
    hydrate_latency_ms_total: float = 0.0
    hydrate_rows: int = 0
    llm_calls: int = 0
    llm_latency_ms_total: float = 0.0
    chat_prompt_tokens: int = 0
    chat_completion_tokens: int = 0
    embed_calls: int = 0
    embed_skipped_unchanged: int = 0
    embed_tokens_est: int = 0
    index_uploads: int = 0
    index_deletes: int = 0
    index_failures: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    sources_routed_total: int = 0
    topk_total: int = 0
    sync_runs: int = 0
    sync_rows_changed: int = 0
    sync_lag_seconds: float = 0.0
    recent_events: Deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))


_lock = threading.Lock()
_counters = _Counters()


def _event(kind: str, **payload: Any) -> None:
    with _lock:
        _counters.recent_events.appendleft(
            {"ts": time.time(), "kind": kind, **payload}
        )


def record_search(latency_ms: float, *, top_k: int, sources: int, cache_hit: bool = False) -> None:
    with _lock:
        _counters.search_queries += 1
        _counters.search_latency_ms_total += latency_ms
        _counters.topk_total += top_k
        _counters.sources_routed_total += sources
        if cache_hit:
            _counters.cache_hits += 1
        else:
            _counters.cache_misses += 1
    _event("search", latency_ms=latency_ms, top_k=top_k, sources=sources, cache_hit=cache_hit)


def record_hydrate(latency_ms: float, rows: int) -> None:
    with _lock:
        _counters.hydrate_calls += 1
        _counters.hydrate_latency_ms_total += latency_ms
        _counters.hydrate_rows += rows
    _event("hydrate", latency_ms=latency_ms, rows=rows)


def record_llm(
    latency_ms: float,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    with _lock:
        _counters.llm_calls += 1
        _counters.llm_latency_ms_total += latency_ms
        _counters.chat_prompt_tokens += prompt_tokens
        _counters.chat_completion_tokens += completion_tokens
    _event(
        "llm",
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def record_embed(*, tokens_est: int = 0, skipped: bool = False) -> None:
    with _lock:
        if skipped:
            _counters.embed_skipped_unchanged += 1
        else:
            _counters.embed_calls += 1
            _counters.embed_tokens_est += tokens_est
    _event("embed", tokens_est=tokens_est, skipped=skipped)


def record_index(*, ok: int = 0, failed: int = 0, deletes: int = 0) -> None:
    with _lock:
        _counters.index_uploads += ok
        _counters.index_failures += failed
        _counters.index_deletes += deletes


def record_sync(*, changed: int, lag_seconds: float = 0.0) -> None:
    with _lock:
        _counters.sync_runs += 1
        _counters.sync_rows_changed += changed
        _counters.sync_lag_seconds = lag_seconds
    _event("sync", changed=changed, lag_seconds=lag_seconds)


def snapshot() -> dict[str, Any]:
    with _lock:
        c = _counters
        sq = max(c.search_queries, 1)
        return {
            "search_queries": c.search_queries,
            "avg_search_latency_ms": round(c.search_latency_ms_total / sq, 2),
            "hydrate_calls": c.hydrate_calls,
            "avg_hydrate_latency_ms": round(
                c.hydrate_latency_ms_total / max(c.hydrate_calls, 1), 2
            ),
            "hydrate_rows": c.hydrate_rows,
            "llm_calls": c.llm_calls,
            "avg_llm_latency_ms": round(c.llm_latency_ms_total / max(c.llm_calls, 1), 2),
            "chat_prompt_tokens": c.chat_prompt_tokens,
            "chat_completion_tokens": c.chat_completion_tokens,
            "embed_calls": c.embed_calls,
            "embed_skipped_unchanged": c.embed_skipped_unchanged,
            "embed_tokens_est": c.embed_tokens_est,
            "index_uploads": c.index_uploads,
            "index_deletes": c.index_deletes,
            "index_failures": c.index_failures,
            "cache_hits": c.cache_hits,
            "cache_misses": c.cache_misses,
            "cache_hit_rate": round(
                c.cache_hits / max(c.cache_hits + c.cache_misses, 1), 3
            ),
            "avg_sources_routed": round(c.sources_routed_total / sq, 2),
            "avg_topk": round(c.topk_total / sq, 2),
            "sync_runs": c.sync_runs,
            "sync_rows_changed": c.sync_rows_changed,
            "sync_lag_seconds": c.sync_lag_seconds,
            "recent_events": list(c.recent_events)[:20],
        }


def reset_metrics() -> None:
    global _counters
    with _lock:
        _counters = _Counters()
