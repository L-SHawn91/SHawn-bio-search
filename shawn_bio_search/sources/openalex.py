"""OpenAlex source module (no API key required)."""

from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Any, Dict, List


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def _openalex_abstract(inv: Any) -> str:
    """Convert OpenAlex inverted abstract to text."""
    if not isinstance(inv, dict):
        return ""
    pos_to_word: Dict[int, str] = {}
    for word, positions in inv.items():
        if not isinstance(positions, list):
            continue
        for p in positions:
            if isinstance(p, int):
                pos_to_word[p] = word
    if not pos_to_word:
        return ""
    max_pos = max(pos_to_word.keys())
    words = [pos_to_word.get(i, "") for i in range(max_pos + 1)]
    return " ".join([w for w in words if w]).strip()


def fetch_openalex(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from OpenAlex."""
    params = {"search": query, "per-page": str(max(1, min(limit, 200)))}
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    rows = data.get("results", [])
    
    out = []
    for r in rows[:limit]:
        authors = [a.get("author", {}).get("display_name") for a in r.get("authorships") or []]
        authors = [a for a in authors if a]
        
        doi_url = r.get("doi")
        doi = doi_url.replace("https://doi.org/", "") if isinstance(doi_url, str) else None
        
        out.append({
            "source": "openalex",
            "id": r.get("id") or "",
            "title": r.get("display_name") or r.get("title") or "",
            "authors": authors,
            "year": int(r.get("publication_year") or 0),
            "doi": doi,
            "url": (r.get("primary_location") or {}).get("landing_page_url") or r.get("id") or "",
            "abstract": _openalex_abstract(r.get("abstract_inverted_index")),
            "citations": int(r.get("cited_by_count") or 0),
        })
    
    return out
