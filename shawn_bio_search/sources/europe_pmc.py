"""Europe PMC source module (no API key required)."""

from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Any, Dict, List


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def fetch_europe_pmc(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from Europe PMC."""
    params = {
        "query": query,
        "format": "json",
        "pageSize": str(max(1, min(limit, 100))),
    }
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    rows = data.get("resultList", {}).get("result", [])
    
    out = []
    for r in rows[:limit]:
        author_str = r.get("authorString") or ""
        authors = [x.strip() for x in author_str.split(",") if x.strip()][:10]
        year = int((r.get("pubYear") or "0")[:4] or 0)
        doi = r.get("doi")
        pid = r.get("id") or ""
        source = r.get("source", "").lower()
        
        out.append({
            "source": "europe_pmc",
            "id": pid,
            "title": r.get("title") or "",
            "authors": authors,
            "year": year,
            "doi": doi,
            "url": f"https://europepmc.org/article/{source}/{pid}" if pid else "",
            "abstract": r.get("abstractText") or "",
            "citations": int(r.get("citedByCount") or 0),
        })
    
    return out
