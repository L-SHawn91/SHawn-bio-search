"""Optional local embedding support via Ollama nomic-embed-text.

Provides cosine similarity scoring as a semantic enhancement to the lexical
overlap pipeline. Gracefully degrades to returning None when Ollama is
unavailable so callers can fall back to overlap_ratio.

Usage:
    from shawn_bio_search.embeddings import embed_texts, cosine_sim

    vecs = embed_texts(["claim text", "abstract sentence"])
    if vecs is not None:
        sim = cosine_sim(vecs[0], vecs[1])
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from .text_utils import _warn_once

_DEFAULT_MODEL = "nomic-embed-text:latest"
_DEFAULT_HOST  = "http://127.0.0.1:11434"
_TIMEOUT       = float(os.getenv("SBS_EMBED_TIMEOUT", "8"))

# ③ Disk-backed in-memory embedding cache
_CACHE_PATH = Path(os.getenv(
    "SBS_EMBED_CACHE",
    str(Path.home() / ".cache" / "sbs_embed_cache.pkl"),
))
_EMBED_CACHE: Dict[str, List[float]] = {}
_CACHE_DIRTY = False


def _load_cache() -> None:
    global _EMBED_CACHE
    try:
        if _CACHE_PATH.exists():
            with open(_CACHE_PATH, "rb") as f:
                _EMBED_CACHE = pickle.load(f)
    except Exception:
        _EMBED_CACHE = {}


def _save_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "wb") as f:
            pickle.dump(_EMBED_CACHE, f)
    except Exception:
        pass


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()[:24]


_load_cache()


def embed_texts(
    texts: List[str],
    *,
    model: str = "",
    host: str = "",
    timeout: float = 0.0,
) -> Optional[List[List[float]]]:
    """Return embeddings for each text, or None if Ollama is unavailable.

    Uses /api/embed (batch endpoint) when available, falls back to
    /api/embeddings (single) when not. Results are cached to disk.
    """
    global _CACHE_DIRTY
    if not texts:
        return []
    _model   = model   or os.getenv("SBS_EMBED_MODEL",   _DEFAULT_MODEL)
    _host    = (host   or os.getenv("SBS_EMBED_HOST",    _DEFAULT_HOST)).rstrip("/")
    _timeout = timeout or _TIMEOUT

    # Split texts into cached vs. needs-fetch
    keys = [_cache_key(_model, t) for t in texts]
    result: List[Optional[List[float]]] = [_EMBED_CACHE.get(k) for k in keys]
    missing_indices = [i for i, v in enumerate(result) if v is None]

    if not missing_indices:
        return result  # type: ignore[return-value]

    missing_texts = [texts[i] for i in missing_indices]

    # Try batch endpoint first (/api/embed, Ollama ≥0.1.34)
    fetched: Optional[List[List[float]]] = None
    try:
        body = json.dumps({"model": _model, "input": missing_texts}).encode()
        req  = urllib.request.Request(
            f"{_host}/api/embed",
            data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=_timeout) as r:
            data = json.loads(r.read())
        embs = data.get("embeddings")
        if embs and len(embs) == len(missing_texts):
            fetched = embs
    except Exception:
        pass

    # Fall back to single /api/embeddings per text
    if fetched is None:
        try:
            fetched = []
            for text in missing_texts:
                body = json.dumps({"model": _model, "prompt": text}).encode()
                req  = urllib.request.Request(
                    f"{_host}/api/embeddings",
                    data=body, headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=_timeout) as r:
                    data = json.loads(r.read())
                emb = data.get("embedding")
                if not emb:
                    _warn_once("embed_fail", f"{_model} unavailable → lexical scoring only (check Ollama or set SBS_EMBED_HOST)")
                    return None
                fetched.append(emb)
        except Exception as _e:
            _warn_once("embed_fail", f"{_model} unavailable → lexical scoring only ({str(_e)[:60]})")
            return None

    # Store newly fetched vectors in cache
    for i, vec in zip(missing_indices, fetched):
        _EMBED_CACHE[keys[i]] = vec
        result[i] = vec
    _CACHE_DIRTY = True
    _save_cache()

    return result  # type: ignore[return-value]


def cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity in [0, 1] (clipped; returns 0.0 on zero-norm input)."""
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    raw = dot / (na * nb)
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))  # map [-1,1] → [0,1]
