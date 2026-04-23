"""OpenAlex source module (no API key required)."""

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


def fetch_source_by_name(venue_name: str, mailto: str | None = None) -> Dict[str, Any] | None:
    """Look up an OpenAlex `source` (journal/venue) by name.

    Returns a dict with id, display_name, h_index, works_count, is_in_doaj,
    summary_stats, x_concepts. Returns None if no match.

    Used by SHawn-paper-mapping classify_venue.py for field-invariant venue
    quality scoring (see paper-mapping/rules/evidence_grading.md).
    """
    if not venue_name or not venue_name.strip():
        return None
    params = {"search": venue_name.strip(), "per-page": "5"}
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/sources?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except Exception:
        return None
    rows = data.get("results", []) or []
    if not rows:
        return None
    # Prefer exact (case-insensitive) display_name match; fall back to top hit.
    target = venue_name.strip().lower()
    best = None
    for r in rows:
        if (r.get("display_name") or "").strip().lower() == target:
            best = r
            break
    if best is None:
        best = rows[0]
    summary = best.get("summary_stats") or {}
    return {
        "id": best.get("id"),                                  # full URL like https://openalex.org/S...
        "id_short": (best.get("id") or "").rsplit("/", 1)[-1], # "S2764455111"
        "display_name": best.get("display_name"),
        "issn_l": best.get("issn_l"),
        "issn": best.get("issn"),
        "host_organization_name": best.get("host_organization_name"),
        "type": best.get("type"),                              # journal | repository | conference | ...
        "is_in_doaj": bool(best.get("is_in_doaj")),
        "is_oa": bool(best.get("is_oa")),
        "works_count": int(best.get("works_count") or 0),
        "cited_by_count": int(best.get("cited_by_count") or 0),
        "h_index": int(summary.get("h_index") or 0),
        "i10_index": int(summary.get("i10_index") or 0),
        "two_yr_mean_citedness": float(summary.get("2yr_mean_citedness") or 0.0),
        "x_concepts": best.get("x_concepts") or [],            # [{display_name, score, level, wikidata}]
    }


def fetch_work_concepts_by_doi(doi: str, mailto: str | None = None) -> Dict[str, Any] | None:
    """Fetch a work's concepts and host_venue from OpenAlex by DOI.

    Returns {concepts: [...], host_venue: {id, display_name, ...}} or None.
    Used when paper.venue is NULL but a DOI is known — lets us recover the
    venue and concepts in one call.
    """
    if not doi:
        return None
    doi = doi.strip().lower()
    if doi.startswith("doi:"):
        doi = doi[4:]
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi, safe='/.')}"
    if mailto:
        url += "?mailto=" + urllib.parse.quote(mailto)
    try:
        data = _get_json(url)
    except Exception:
        return None
    host = data.get("primary_location", {}).get("source") or {}
    authors = [a.get("author", {}).get("display_name")
               for a in data.get("authorships") or []]
    authors = [a for a in authors if a]
    return {
        "concepts": data.get("concepts") or [],
        "host_venue_id": host.get("id"),
        "host_venue_display_name": host.get("display_name"),
        "host_venue_issn_l": host.get("issn_l"),
        "host_venue_type": host.get("type"),
        "is_preprint": (host.get("type") == "repository") or
                       (doi.startswith("10.1101/") or doi.startswith("10.21203/")),
        # Added 2026-04-23 for paper-mapping audit_flagged_clusters.py — lets
        # the auditor cross-check whether paper.doi actually points to
        # paper.title or to a different work entirely.
        "title": data.get("display_name") or data.get("title"),
        "authors": authors,
        "year": int(data.get("publication_year") or 0),
    }


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
