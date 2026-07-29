"""
Embedding helper — calls Azure OpenAI text-embedding-3-small.
Produces a 1536-dimensional vector for a given text.

Usage:
    from app.search.embeddings import embed_text
    vector = embed_text("pending handover documents")   # list[float], len 1536
"""
import hashlib
import logging
import time
from threading import Lock
from typing import List, Optional, Dict

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536          # text-embedding-3-small fixed output dimension
MAX_CHARS = 8000              # safe input limit (model allows ~8k tokens ≈ 32k chars)

# Small in-process cache so we never embed the same text twice during one reindex
_embed_cache: Dict[str, List[float]] = {}

# Locks for texts currently being embedded, so concurrent callers asking for the
# same text (the multi-database fan-out embeds the query once per source) wait
# for the first result instead of each paying an Azure round trip.
_inflight: Dict[str, Lock] = {}
_inflight_lock = Lock()

_client = None
_client_lock = Lock()


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _get_client():
    # Prefer a dedicated embedding endpoint/key if configured,
    # otherwise fall back to the shared chat resource.
    global _client
    if _client is not None:
        return _client
    endpoint = settings.AZURE_OPENAI_EMBEDDING_ENDPOINT or settings.AZURE_OPENAI_ENDPOINT
    key = settings.AZURE_OPENAI_EMBEDDING_KEY or settings.AZURE_OPENAI_KEY
    if not endpoint or not key:
        return None
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from openai import AzureOpenAI
            _client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=key,
                api_version="2024-02-01",
            )
        except Exception as e:
            logger.error(f"Embedding client init failed: {e}")
            return None
    return _client


def embed_text(text: str) -> Optional[List[float]]:
    """
    Return a 1536-d vector for *text*, or None if Azure OpenAI is not configured.
    Results are cached in-process for the lifetime of the request/task.
    """
    if not text or not text.strip():
        return None

    text = text.strip()[:MAX_CHARS]
    key = _cache_key(text)
    if key in _embed_cache:
        return _embed_cache[key]

    client = _get_client()
    if client is None:
        return None

    with _inflight_lock:
        lock = _inflight.get(key)
        owns_slot = lock is None
        if owns_slot:
            lock = Lock()
            _inflight[key] = lock

    with lock:
        if key in _embed_cache:
            return _embed_cache[key]
        try:
            resp = client.embeddings.create(
                model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                input=text,
            )
            vector: List[float] = resp.data[0].embedding
            _embed_cache[key] = vector
            return vector
        except Exception as e:
            logger.warning(f"Embedding call failed (text[:60]='{text[:60]}'): {e}")
            return None
        finally:
            if owns_slot:
                with _inflight_lock:
                    _inflight.pop(key, None)


def embed_batch(texts: List[str], delay_ms: int = 0) -> List[Optional[List[float]]]:
    """
    Embed a list of texts.  Returns a parallel list of vectors (or None on failure).
    delay_ms adds a small sleep between calls to avoid rate-limit bursts.
    """
    results: List[Optional[List[float]]] = []
    for t in texts:
        results.append(embed_text(t))
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
    return results


def clear_embed_cache():
    _embed_cache.clear()
