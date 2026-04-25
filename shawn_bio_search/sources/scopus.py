"""Scopus source module (requires API key)."""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def _get_json(url: str, headers: Dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def _headers() -> Optional[Dict[str, str]]:
    api_key = os.getenv("SCOPUS_API_KEY")
    if not api_key:
        return None
    headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}
    inst = os.getenv("SCOPUS_INSTTOKEN")
    if inst:
        headers["X-ELS-Insttoken"] = inst
    return headers


def _extract_authors(entry: Dict[str, Any]) -> List[str]:
    """Pull full author list from a Scopus entry, falling back to dc:creator."""
    author_block = entry.get("author")
    authors: List[str] = []
    if isinstance(author_block, list):
        for a in author_block:
            if not isinstance(a, dict):
                continue
            label = a.get("authname") or a.get("ce:indexed-name") or a.get("given-name")
            if label:
                authors.append(str(label))
    if not authors:
        creator = entry.get("dc:creator")
        if creator:
            authors = [str(creator)]
    return authors


def fetch_scopus(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from Scopus (requires SCOPUS_API_KEY).

    Uses `view=COMPLETE` so abstract (dc:description), journal name, and full
    author list come back in the search response.
    """
    headers = _headers()
    if not headers:
        return []

    url = (
        "https://api.elsevier.com/content/search/scopus?"
        + urllib.parse.urlencode({
            "query": query,
            "count": str(limit),
            "sort": "-citedby-count",
            "view": "COMPLETE",
        })
    )

    try:
        data = _get_json(url, headers)
    except Exception:
        return []

    entries = data.get("search-results", {}).get("entry", [])

    out = []
    for e in entries:
        out.append({
            "source": "scopus",
            "id": e.get("dc:identifier") or "",
            "title": e.get("dc:title") or "",
            "authors": _extract_authors(e),
            "year": int((e.get("prism:coverDate") or "0")[:4] or 0),
            "doi": e.get("prism:doi"),
            "journal": e.get("prism:publicationName") or "",
            "url": e.get("prism:url") or "",
            "abstract": e.get("dc:description") or "",
            "citations": int(e.get("citedby-count") or 0),
        })

    return out


def search_scopus_authors(name: str, limit: int = 10, affiliation: str = "") -> List[Dict[str, Any]]:
    """Search Scopus author profiles by name/affiliation."""
    headers = _headers()
    if not headers or not name.strip():
        return []

    query = f"authlast({name})"
    parts = [p.strip() for p in name.replace(",", " ").split() if p.strip()]
    if len(parts) >= 2:
        given = parts[0]
        family = parts[-1]
        query = f"authlast({family}) and authfirst({given})"
    if affiliation.strip():
        query += f" and affil({affiliation})"

    url = (
        "https://api.elsevier.com/content/search/author?"
        + urllib.parse.urlencode({"query": query, "count": str(limit), "sort": "document-count"})
    )

    try:
        data = _get_json(url, headers)
    except Exception:
        return []

    entries = data.get("search-results", {}).get("entry", [])
    out = []
    for e in entries:
        out.append({
            "source": "scopus_author",
            "author_id": (e.get("dc:identifier") or "").replace("AUTHOR_ID:", ""),
            "name": e.get("preferred-name", {}).get("indexed-name") or e.get("dc:identifier") or "",
            "surname": e.get("preferred-name", {}).get("surname") or "",
            "given_name": e.get("preferred-name", {}).get("given-name") or "",
            "affiliation": e.get("affiliation-current", {}).get("affiliation-name") or "",
            "document_count": int(e.get("document-count") or 0),
            "citation_count": int(e.get("citation-count") or 0),
            "orcid": e.get("orcid") or "",
            "eid": e.get("eid") or "",
        })
    return out


def fetch_scopus_author_publications(author_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch publications for a specific Scopus author id."""
    if not str(author_id).strip():
        return []
    return fetch_scopus(f"AU-ID({author_id})", limit)
