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


def fetch_crossref_by_doi(doi: str) -> Dict[str, Any] | None:
    """Direct Crossref DOI lookup via /works/{doi}.

    Returns one record dict or None. Use when fetch_by_doi (PubMed) returns
    empty for non-PubMed DOIs (BMC, Frontiers, MDPI, Wiley, Elsevier, etc.).
    """
    if not doi:
        return None
    d = doi.strip().lower().replace("https://doi.org/", "")
    url = f"https://api.crossref.org/works/{urllib.parse.quote(d, safe='')}"
    try:
        data = _get_json(url)
    except Exception:
        return None
    msg = data.get("message", {}) if isinstance(data, dict) else {}
    if not msg:
        return None
    authors = []
    for a in msg.get("author") or []:
        name = " ".join([x for x in [a.get("given"), a.get("family")] if x])
        if name:
            authors.append(name)
    year = 0
    dp = (msg.get("issued") or {}).get("date-parts") or []
    if dp and isinstance(dp[0], list) and dp[0]:
        year = int(dp[0][0] or 0)
    title_list = msg.get("title") or []
    abs_raw = msg.get("abstract") or ""
    abs_text = re.sub(r"<[^>]+", " ", html.unescape(abs_raw)).strip() if abs_raw else ""
    return {
        "source": "crossref",
        "id": msg.get("DOI") or "",
        "title": title_list[0] if title_list else "",
        "authors": authors,
        "first_author": authors[0] if authors else "",
        "year": year,
        "doi": msg.get("DOI"),
        "url": (msg.get("URL") or "").strip(),
        "abstract": re.sub(r"\s+", " ", abs_text),
        "container": (msg.get("container-title") or [""])[0],
        "citations": int(msg.get("is-referenced-by-count") or 0),
    }


def lookup_doi_by_author_keywords(author: str | None,
                                   title: str | None,
                                   year: int | str | None = None,
                                   per_page: int = 5) -> Dict[str, Any] | None:
    """Crossref DOI lookup tuned for SHawn corpus recovery.

    Builds a query from author last-name + first 6 distinctive title words
    + year. Re-ranks Crossref results by Jaccard(title) + author-substring
    + year-match. Returns the best candidate dict or None.

    Used by SHawn-paper-mapping recover_doi_unified.py as a Tier-3 fallback
    when Zotero has no DOI and OpenAlex is rate-limited.
    """
    parts: list[str] = []
    if author:
        first = author.strip().split()[0].rstrip(",")
        if first and first.lower() not in ("?", "anon", "anonymous"):
            parts.append(first)
    if title:
        # Take first 6 words longer than 3 chars (drop articles/prepositions)
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", title)
                 if len(w) > 3]
        parts.extend(words[:6])
    if year:
        try:
            yi = int(str(year)[:4])
            if 1900 < yi < 2100:
                parts.append(str(yi))
        except (TypeError, ValueError):
            pass
    if not parts:
        return None
    query = " ".join(parts)

    try:
        results = fetch_crossref(query, limit=per_page)
    except Exception:
        return None
    if not results:
        return None

    # Re-rank: Jaccard(title) + author boost + year boost
    target_words = set((title or "").lower().split())
    author_first = (author or "").strip().split()[0].lower().rstrip(",") if author else ""
    try:
        year_int = int(str(year)[:4]) if year else 0
    except (TypeError, ValueError):
        year_int = 0

    scored = []
    for r in results:
        cand_title = r.get("title") or ""
        if not cand_title:
            continue
        cand_words = set(cand_title.lower().split())
        if not cand_words:
            continue
        jaccard = (len(target_words & cand_words) / max(1, len(target_words | cand_words))
                   if target_words else 0.0)
        cand_author_blob = " ".join(r.get("authors") or []).lower()
        author_match = bool(author_first and author_first in cand_author_blob)
        cand_year = int(r.get("year") or 0)
        year_match = bool(year_int and abs(cand_year - year_int) <= 2)
        score = jaccard + (0.30 if author_match else 0) + (0.10 if year_match else 0)
        scored.append((score, jaccard, author_match, year_match, r))
    if not scored:
        return None
    scored.sort(reverse=True, key=lambda x: x[0])
    boosted, jac, am, ym, top = scored[0]
    return {
        "doi": top.get("doi"),
        "title": top.get("title"),
        "authors": top.get("authors", [])[:5],
        "year": top.get("year"),
        "similarity_score": round(jac, 3),
        "boosted_score": round(boosted, 3),
        "author_match": am,
        "year_match": ym,
    }


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
