"""Kaggle dataset source (requires KAGGLE_USERNAME + KAGGLE_KEY).

Replaces the previous shell-out from `scripts/run_paper_writing_mode_v2.sh`
that just dumped `kaggle datasets list` markdown. This module talks to the
Kaggle REST endpoint directly with HTTP Basic auth and emits records that
match the dataset schema used by `scripts/dataset_search.py` so Kaggle
results dedupe and rank alongside GEO / SRA / OmicsDI / HuggingFace.

Why direct REST vs the official `kaggle` Python SDK
- Zero new runtime dependency. The SDK pulls in `bleach`, `python-slugify`,
  `requests`, `tqdm`, `urllib3`, `python-dateutil`. We only need search.
- Avoids the SDK's hard requirement that ~/.kaggle/kaggle.json exists with
  perm 600. Env vars are enough for both CLI and library use.

API: https://www.kaggle.com/docs/api  (the `/datasets/list` route)
Credentials: https://www.kaggle.com/settings → Create New API Token.
"""

from __future__ import annotations

import base64
import os
import urllib.parse
from typing import Any, Dict, List, Optional

from ._http import http_json

_BASE = "https://www.kaggle.com/api/v1/datasets/list"


def _credentials() -> Optional[Dict[str, str]]:
    user = os.getenv("KAGGLE_USERNAME")
    key = os.getenv("KAGGLE_KEY")
    if not user or not key:
        return None
    token = base64.b64encode(f"{user}:{key}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _year_from_iso(s: Optional[str]) -> Optional[int]:
    if not s or not isinstance(s, str) or len(s) < 4:
        return None
    try:
        return int(s[:4])
    except ValueError:
        return None


def _truncate(text: Optional[str], limit: int = 600) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


_BIO_HINT_TOKENS = (
    "human", "mouse", "rat", "zebrafish", "drosophila", "yeast",
    "patient", "clinical", "medical", "disease",
)


def _organism_from_tags(tags: Any) -> str:
    if not isinstance(tags, list):
        return ""
    out: List[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            name = str(tag.get("name") or tag.get("ref") or "")
        else:
            name = str(tag or "")
        lower = name.lower()
        if any(token in lower for token in _BIO_HINT_TOKENS):
            out.append(name)
    return ", ".join(out)


def _assay_from_tags(tags: Any) -> str:
    """Pick the first non-trivial tag as a proxy for "kind of data"."""
    if not isinstance(tags, list):
        return ""
    for tag in tags:
        name = tag.get("name") if isinstance(tag, dict) else tag
        if name and isinstance(name, str) and not name.lower().startswith("subject"):
            return name
    return ""


def fetch_kaggle_datasets(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search Kaggle for public datasets matching `query`.

    Returns `[]` (with no HTTP call) when credentials are missing or when the
    query is empty. Returns `[]` (no raise) on HTTP failures, matching the
    failure model of every other dataset source.
    """
    if not query or not query.strip():
        return []
    creds = _credentials()
    if creds is None:
        return []

    params = {"search": query, "page": "1"}
    url = f"{_BASE}?{urllib.parse.urlencode(params)}"

    try:
        rows = http_json(url, headers=creds)
    except Exception:
        return []

    if not isinstance(rows, list):
        return []

    out: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        ref = row.get("ref") or ""
        if not ref:
            continue
        tags = row.get("tags") or []
        title = row.get("title") or ref
        subtitle = row.get("subtitle") or ""
        description = row.get("description") or subtitle
        url_field = row.get("url") or f"https://www.kaggle.com/datasets/{ref}"
        if url_field and not url_field.startswith("http"):
            url_field = f"https://www.kaggle.com{url_field}"
        out.append({
            "repository": "kaggle",
            "accession": ref,
            "title": title,
            "organism": _organism_from_tags(tags),
            "assay": _assay_from_tags(tags),
            "sample_count": None,
            "disease": "",
            "tissue": "",
            "summary": _truncate(description),
            "year": _year_from_iso(row.get("lastUpdated") or row.get("creationDate")),
            "raw_available": True,
            "processed_available": True,
            "downloads": int(row.get("downloadCount") or 0),
            "votes": int(row.get("voteCount") or 0),
            "owner": row.get("ownerName") or row.get("creatorName") or "",
            "url": url_field,
        })
    return out
