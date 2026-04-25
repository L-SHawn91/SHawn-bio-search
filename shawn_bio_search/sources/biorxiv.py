"""bioRxiv source module (no API key required)."""

from __future__ import annotations

import time
import urllib.request
from typing import Any, Dict, List, Set


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def _tokenize(text: str) -> Set[str]:
    import re
    return set(re.findall(r"[a-zA-Z0-9]{3,}", (text or "").lower()))


def fetch_biorxiv(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch preprints from bioRxiv (fetches recent and filters locally)."""
    end_date = "2030-12-31"
    start_date = "2023-01-01"
    cursor = 0
    batch_size = 100
    
    all_papers = []
    query_terms = _tokenize(query)
    
    for _ in range(3):
        if len(all_papers) >= limit * 3:
            break
        
        url = f"https://api.biorxiv.org/pubs/{start_date}/{end_date}/{cursor}/{batch_size}"
        
        try:
            data = _get_json(url)
            collection = data.get("collection", [])
            
            if not collection:
                break
            
            for item in collection:
                title = item.get("title", "")
                abstract = item.get("abstract", "")
                
                content = (title + " " + abstract).lower()
                if not any(term in content for term in query_terms):
                    continue
                
                authors_list = item.get("authors", "")
                authors = [a.strip() for a in authors_list.split(",") if a.strip()][:10]
                
                doi = item.get("doi", "")
                biorxiv_url = item.get("biorxiv_url", "")
                url_link = f"https://www.biorxiv.org/content/{doi}" if doi else biorxiv_url
                
                all_papers.append({
                    "source": "biorxiv",
                    "id": doi or biorxiv_url,
                    "title": title,
                    "authors": authors,
                    "year": int((item.get("date", "") or "0000")[:4] or 0),
                    "doi": doi,
                    "url": url_link,
                    "abstract": abstract,
                    "citations": 0,
                })
            
            cursor += batch_size
            time.sleep(1.1)  # Rate limit
            
        except Exception:
            break
    
    return all_papers[:limit]
