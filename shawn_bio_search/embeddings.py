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

import json
import math
import os
import urllib.error
import urllib.request
from typing import List, Optional

from .text_utils import _warn_once

_DEFAULT_MODEL = "nomic-embed-text:latest"
_DEFAULT_HOST  = "http://127.0.0.1:11434"
_TIMEOUT       = float(os.getenv("SBS_EMBED_TIMEOUT", "8"))


def embed_texts(
    texts: List[str],
    *,
    model: str = "",
    host: str = "",
    timeout: float = 0.0,
) -> Optional[List[List[float]]]:
    """Return embeddings for each text, or None if Ollama is unavailable.

    Uses /api/embed (batch endpoint) when available, falls back to
    /api/embeddings (single) when not.
    """
    if not texts:
        return []
    _model   = model   or os.getenv("SBS_EMBED_MODEL",   _DEFAULT_MODEL)
    _host    = (host   or os.getenv("SBS_EMBED_HOST",    _DEFAULT_HOST)).rstrip("/")
    _timeout = timeout or _TIMEOUT

    # Try batch endpoint first (/api/embed, Ollama ≥0.1.34)
    try:
        body = json.dumps({"model": _model, "input": texts}).encode()
        req  = urllib.request.Request(
            f"{_host}/api/embed",
            data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=_timeout) as r:
            data = json.loads(r.read())
        embs = data.get("embeddings")
        if embs and len(embs) == len(texts):
            return embs
    except Exception:
        pass

    # Fall back to single /api/embeddings per text
    try:
        result = []
        for text in texts:
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
            result.append(emb)
        return result
    except Exception as _e:
        _warn_once("embed_fail", f"{_model} unavailable → lexical scoring only ({str(_e)[:60]})")
        return None


def cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity in [0, 1] (clipped; returns 0.0 on zero-norm input)."""
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    raw = dot / (na * nb)
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))  # map [-1,1] → [0,1]
