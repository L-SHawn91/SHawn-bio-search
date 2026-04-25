"""Semantic Scholar source module (API key recommended)."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List


API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,year,externalIds,url,abstract,citationCount,openAccessPdf"
_MIN_INTERVAL_SECONDS = 1.1
_LAST_CALL_AT = 0.0


def _rate_limit_wait() -> None:
    global _LAST_CALL_AT
    now = time.monotonic()
    elapsed = now - _LAST_CALL_AT
    if elapsed < _MIN_INTERVAL_SECONDS:
        time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
    _LAST_CALL_AT = time.monotonic()


def _get_json(url: str, headers: Dict[str, str] | None = None) -> Any:
    _rate_limit_wait()
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return __import__("json").loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = max(float(retry_after), _MIN_INTERVAL_SECONDS) if retry_after else 2.0
            except ValueError:
                delay = 2.0
            time.sleep(delay)
            _rate_limit_wait()
            with urllib.request.urlopen(req, timeout=30) as resp:
                return __import__("json").loads(resp.read().decode("utf-8"))
        raise


def fetch_semanticscholar(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from Semantic Scholar.

    Optional environment variables:
    - SEMANTIC_SCHOLAR_API_KEY
    - S2_API_KEY
    """
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY")
    params = {
        "query": query,
        "limit": str(max(1, min(limit, 100))),
        "fields": FIELDS,
    }
    headers: Dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    url = API_URL + "?" + urllib.parse.urlencode(params)
    data = _get_json(url, headers=headers)
    rows = data.get("data", [])

    out = []
    for r in rows[:limit]:
        external_ids = r.get("externalIds") or {}
        doi = external_ids.get("DOI") or external_ids.get("Doi")
        authors = [a.get("name") for a in (r.get("authors") or []) if a.get("name")]
        oa_pdf = (r.get("openAccessPdf") or {}).get("url")
        out.append({
            "source": "semantic_scholar",
            "id": r.get("paperId") or r.get("corpusId") or "",
            "title": r.get("title") or "",
            "authors": authors,
            "year": int(r.get("year") or 0),
            "doi": doi,
            "url": r.get("url") or oa_pdf or (f"https://www.semanticscholar.org/paper/{r.get('paperId')}" if r.get("paperId") else ""),
            "abstract": r.get("abstract") or "",
            "citations": int(r.get("citationCount") or 0),
        })

    return out
