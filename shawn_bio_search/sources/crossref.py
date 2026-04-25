"""Crossref source module (no API key required)."""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def fetch_crossref(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from Crossref."""
    params = {"query": query, "rows": str(max(1, min(limit, 100)))}
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    rows = data.get("message", {}).get("items", [])
    
    out = []
    for r in rows[:limit]:
        authors = []
        for a in r.get("author") or []:
            name = " ".join([x for x in [a.get("given"), a.get("family")] if x])
            if name:
                authors.append(name)
        
        year = 0
        dp = (r.get("issued") or {}).get("date-parts") or []
        if dp and isinstance(dp[0], list) and dp[0]:
            year = int(dp[0][0] or 0)
        
        doi = r.get("DOI")
        title_list = r.get("title") or []
        abs_raw = r.get("abstract") or ""
        abs_text = re.sub(r"<[^>]+", " ", html.unescape(abs_raw)).strip() if abs_raw else ""
        
        out.append({
            "source": "crossref",
            "id": doi or r.get("URL") or "",
            "title": title_list[0] if title_list else "",
            "authors": authors,
            "year": year,
            "doi": doi,
            "url": r.get("URL") or "",
            "abstract": re.sub(r"\s+", " ", abs_text),
            "citations": int(r.get("is-referenced-by-count") or 0),
        })
    
    return out
