"""Unpaywall source module (free; email recommended).

Unpaywall indexes open-access versions of scholarly articles. It supports both
lookup by DOI (primary use) and a text search endpoint. Treat results as OA
enrichment — citation counts are not returned.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ._http import build_url, http_json

_API_SEARCH = "https://api.unpaywall.org/v2/search"
_API_LOOKUP = "https://api.unpaywall.org/v2/"


def _email() -> str:
    """Return the configured email, or empty string if none is set.

    Unpaywall requires an email parameter. Callers should skip the source when
    this returns empty rather than substituting a fake address.
    """
    return os.getenv("UNPAYWALL_EMAIL") or os.getenv("CROSSREF_EMAIL") or ""


def _oa_url(oa_location: Optional[Dict[str, Any]]) -> str:
    if not isinstance(oa_location, dict):
        return ""
    return oa_location.get("url_for_pdf") or oa_location.get("url") or ""


def _normalize(r: Dict[str, Any]) -> Dict[str, Any]:
    doi = r.get("doi") or ""
    year = int(r.get("year") or 0)
    authors: List[str] = []
    for a in (r.get("z_authors") or []):
        if not isinstance(a, dict):
            continue
        given = a.get("given") or ""
        family = a.get("family") or ""
        name = (given + " " + family).strip()
        if name:
            authors.append(name)

    best_oa = r.get("best_oa_location")
    first_oa = (r.get("oa_locations") or [None])[0]
    url_best = _oa_url(best_oa) or _oa_url(first_oa) or (f"https://doi.org/{doi}" if doi else "")

    return {
        "source": "unpaywall",
        "id": doi,
        "title": r.get("title") or "",
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": url_best,
        "abstract": r.get("abstract") or "",
        "citations": 0,
        "is_oa": bool(r.get("is_oa")),
        "oa_status": r.get("oa_status") or "",
    }


def fetch_unpaywall(query: str, limit: int) -> List[Dict[str, Any]]:
    """Text search Unpaywall (title/abstract keyword match).

    Skipped silently when neither UNPAYWALL_EMAIL nor CROSSREF_EMAIL is set —
    Unpaywall requires a real email for its polite-pool policy.
    """
    email = _email()
    if not email or not query.strip():
        return []

    url = build_url(_API_SEARCH, {
        "query": query,
        "is_oa": "true",
        "email": email,
    })

    try:
        data = http_json(url, timeout=30)
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for item in (data.get("results") or [])[:limit]:
        r = item.get("response") if isinstance(item, dict) else None
        if not isinstance(r, dict):
            continue
        out.append(_normalize(r))
    return out


def fetch_unpaywall_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    """Direct DOI lookup — useful for enriching records from other sources."""
    email = _email()
    if not email or not doi.strip():
        return None
    url = _API_LOOKUP + doi.strip() + "?" + build_url("", {"email": email}).lstrip("?")
    try:
        data = http_json(url, timeout=30)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _normalize(data)
