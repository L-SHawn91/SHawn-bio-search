"""F1000Research source module (free, no API key).

F1000Research publishes open-access articles with transparent peer review.
Uses the Crossref API filtered by the F1000Research ISSN prefixes, which is the
most reliable structured entry point.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from ._http import build_url, http_json

_CROSSREF_WORKS = "https://api.crossref.org/works"
# F1000Research top-level ISSN (member 4443). Accepted as a `member:` filter.
_CROSSREF_MEMBER = "4443"


def _authors(item: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for a in (item.get("author") or []):
        if not isinstance(a, dict):
            continue
        given = a.get("given") or ""
        family = a.get("family") or ""
        name = (given + " " + family).strip()
        if name:
            out.append(name)
    return out


def _year(item: Dict[str, Any]) -> int:
    for key in ("published-print", "published-online", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return 0


def fetch_f1000research(query: str, limit: int) -> List[Dict[str, Any]]:
    if not query.strip():
        return []

    headers: Dict[str, str] = {}
    email = os.getenv("CROSSREF_EMAIL")
    if email:
        headers["User-Agent"] = f"SHawn-bio-search/0.1 (mailto:{email})"

    url = build_url(_CROSSREF_WORKS, {
        "query": query,
        "filter": f"member:{_CROSSREF_MEMBER}",
        "rows": max(1, min(limit, 50)),
        "select": "DOI,title,author,issued,published-print,published-online,abstract,URL,is-referenced-by-count,container-title",
    })

    try:
        data = http_json(url, headers=headers, timeout=30)
    except Exception:
        return []

    items = (data.get("message") or {}).get("items") or []
    out: List[Dict[str, Any]] = []
    for item in items[:limit]:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        container_list = item.get("container-title") or []
        journal = container_list[0] if container_list else "F1000Research"

        # Crossref abstracts are JATS XML; strip tags for consistency.
        abstract = item.get("abstract") or ""
        if abstract:
            import re
            abstract = re.sub(r"<[^>]+>", " ", abstract)
            abstract = re.sub(r"\s+", " ", abstract).strip()

        doi = item.get("DOI") or ""
        out.append({
            "source": "f1000research",
            "id": doi,
            "title": title,
            "authors": _authors(item),
            "year": _year(item),
            "doi": doi,
            "journal": journal,
            "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            "abstract": abstract,
            "citations": int(item.get("is-referenced-by-count") or 0),
        })

    return out
