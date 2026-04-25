"""Google Scholar source module (requires SerpAPI key)."""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def fetch_google_scholar(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from Google Scholar via SerpAPI (requires SERPAPI_API_KEY)."""
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        return []
    
    params = {
        "engine": "google_scholar",
        "q": query,
        "num": str(min(limit, 20)),
        "api_key": key,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    
    try:
        data = _get_json(url)
    except Exception:
        return []
    
    out = []
    for item in data.get("organic_results", [])[:limit]:
        pub = item.get("publication_info", {}) or {}
        authors = []
        for a in pub.get("authors") or []:
            if isinstance(a, dict):
                n = a.get("name")
                if n:
                    authors.append(n)
            elif isinstance(a, str):
                authors.append(a)
        
        out.append({
            "source": "google_scholar",
            "id": str(item.get("result_id") or ""),
            "title": item.get("title") or "",
            "authors": authors,
            "year": int(pub.get("year") or 0),
            "doi": None,
            "url": item.get("link") or "",
            "abstract": item.get("snippet") or "",
            "citations": int((item.get("inline_links") or {}).get("cited_by", {}).get("total") or 0),
        })
    
    return out
