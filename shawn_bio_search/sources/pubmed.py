"""PubMed/NCBI source module with advanced field-tag search support."""

from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


def _get_json(url: str, headers: Dict[str, str] | None = None) -> Any:
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def _get_xml(url: str) -> ET.Element:
    """Fetch and parse XML from URL."""
    xml_text = urllib.request.urlopen(url, timeout=30).read().decode("utf-8", "ignore")
    return ET.fromstring(xml_text)


def _base_url() -> str:
    return "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _api_params(extra: Dict[str, str] | None = None) -> Dict[str, str]:
    """Build params dict with optional API key."""
    params: Dict[str, str] = {"db": "pubmed"}
    key = os.getenv("NCBI_API_KEY")
    if key:
        params["api_key"] = key
    if extra:
        params.update(extra)
    return params


# ------------------------------------------------------------------ #
# 1. PMID direct lookup
# ------------------------------------------------------------------ #
def fetch_by_pmid(pmids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full metadata for known PMIDs."""
    if not pmids:
        return []
    return _fetch_details(pmids)


# ------------------------------------------------------------------ #
# 2. DOI-based search
# ------------------------------------------------------------------ #
def fetch_by_doi(doi: str) -> List[Dict[str, Any]]:
    """Find a paper by its DOI."""
    return _esearch_and_fetch(f"{doi}[doi]", limit=1)


# ------------------------------------------------------------------ #
# 3. Citation verification mode
# ------------------------------------------------------------------ #
def verify_citation(
    first_author: str,
    year: str,
    context_keywords: List[str] | None = None,
    context_sentence: str | None = None,
    min_context_score: float = 0.3,
    use_crossref: bool = True,
    use_semanticscholar: bool = True,
) -> List[Dict[str, Any]]:
    """Find a specific paper by author + year with progressive fallback,
    context-match scoring, and cross-source verification.

    Pipeline:
      Phase 1 — PubMed field-tag strategies (5 levels, strict → broad)
      Phase 2 — If no HIGH match, try Crossref by author+year+keywords
      Phase 3 — If still no HIGH match, try Semantic Scholar

    Each result is scored against context_keywords and context_sentence.
    Results are sorted by context_score (descending).
    """
    strategies = _build_verification_strategies(first_author, year, context_keywords)

    all_candidates: List[Dict[str, Any]] = []
    strategies_tried: List[str] = []

    # --- Phase 1: PubMed ---
    for strategy_name, query in strategies:
        results = _esearch_and_fetch(query, limit=10)
        strategies_tried.append(f"pubmed:{strategy_name}")

        for r in results:
            if any(c.get("pmid") == r["pmid"] for c in all_candidates):
                continue
            r["_search_strategy"] = f"pubmed:{strategy_name}"
            r["_context_score"] = _compute_context_score(
                r, context_keywords, context_sentence
            )
            all_candidates.append(r)

        best_so_far = max(
            (c["_context_score"] for c in all_candidates), default=0.0
        )
        if best_so_far >= 0.6:
            break

    # --- Phase 2: Crossref fallback ---
    best_so_far = max(
        (c["_context_score"] for c in all_candidates), default=0.0
    )
    if use_crossref and best_so_far < 0.5:
        strategies_tried.append("crossref")
        crossref_results = _crossref_search(first_author, year, context_keywords)
        for r in crossref_results:
            if any(_same_paper(c, r) for c in all_candidates):
                continue
            r["_search_strategy"] = "crossref"
            r["_context_score"] = _compute_context_score(
                r, context_keywords, context_sentence
            )
            all_candidates.append(r)

    # --- Phase 3: Semantic Scholar fallback ---
    best_so_far = max(
        (c["_context_score"] for c in all_candidates), default=0.0
    )
    if use_semanticscholar and best_so_far < 0.5:
        strategies_tried.append("semantic_scholar")
        s2_results = _semantic_scholar_search(first_author, year, context_keywords)
        for r in s2_results:
            if any(_same_paper(c, r) for c in all_candidates):
                continue
            r["_search_strategy"] = "semantic_scholar"
            r["_context_score"] = _compute_context_score(
                r, context_keywords, context_sentence
            )
            all_candidates.append(r)

    # Sort by context score
    all_candidates.sort(key=lambda x: x["_context_score"], reverse=True)

    for c in all_candidates:
        c["_strategies_tried"] = strategies_tried
        c["_verification_confidence"] = _score_to_confidence(c["_context_score"])

    return all_candidates


def _compute_context_score(
    paper: Dict[str, Any],
    keywords: List[str] | None,
    context_sentence: str | None,
) -> float:
    """Score how well a paper can be identified as the intended citation.

    PURPOSE: Help find the RIGHT paper among candidates with the same author+year.
    This is NOT a judgment of whether the citation is appropriate for the sentence.
    The author's citation choice is always assumed correct.

    Scoring:
      - author+year match from search strategy → base 0.35 (assumed correct)
      - keyword overlap for disambiguation among same-author papers (0-0.35)
      - species/domain overlap as soft signal, NO penalty (0-0.15)
      - MeSH overlap (0-0.15)
    """
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()
    mesh = [m.lower() for m in paper.get("mesh_terms", [])]
    paper_text = f"{title} {abstract}"

    # Base score: if we found this paper via author+year search, it's likely correct
    score = 0.35

    # --- Keyword overlap (0-0.35) — for disambiguation only ---
    context_terms: List[str] = []
    if keywords:
        context_terms.extend([k.lower().rstrip("*") for k in keywords])
    if context_sentence:
        words = re.findall(r'[a-z]{4,}', context_sentence.lower())
        stops = {'with', 'from', 'that', 'this', 'have', 'been', 'were', 'also',
                 'their', 'these', 'which', 'into', 'between', 'through', 'during',
                 'including', 'under', 'than', 'both', 'more', 'each', 'most'}
        context_terms.extend([w for w in words if w not in stops])

    if context_terms:
        unique_terms = list(set(context_terms))
        matches = sum(1 for t in unique_terms if t in paper_text)
        if unique_terms:
            score += 0.35 * (matches / len(unique_terms))

    # --- Species/domain signal — bonus only, NO penalty ---
    species_terms = ['bovine', 'porcine', 'canine', 'feline', 'equine', 'ovine',
                     'human', 'mouse', 'rat', 'primate', 'macaque',
                     'cow', 'pig', 'dog', 'cat', 'horse', 'sheep']
    context_species = [s for s in species_terms if s in ' '.join(context_terms)]
    paper_species = [s for s in species_terms if s in paper_text]
    if context_species and paper_species:
        if set(context_species) & set(paper_species):
            score += 0.10

    domain_terms = ['organoid', 'endometri', 'decidual', 'implant', 'placent',
                    'uterine', 'pregnancy', 'reproductive', 'embryo', 'conceptus',
                    'bovine', 'porcine', 'fertility', 'hormone']
    context_domain = [d for d in domain_terms if d in ' '.join(context_terms)]
    paper_domain = [d for d in domain_terms if d in paper_text]
    if context_domain and paper_domain:
        overlap = len(set(context_domain) & set(paper_domain))
        score += 0.05 * min(1.0, overlap / max(len(context_domain), 1))

    # --- MeSH overlap (0-0.15) ---
    if mesh and context_terms:
        mesh_text = ' '.join(mesh)
        mesh_matches = sum(1 for t in context_terms if t in mesh_text)
        score += 0.2 * min(1.0, mesh_matches / max(len(context_terms), 1))

    return max(0.0, min(1.0, score))


def _same_paper(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Check if two result dicts refer to the same paper."""
    if a.get("doi") and b.get("doi"):
        return a["doi"].lower().strip() == b["doi"].lower().strip()
    if a.get("pmid") and b.get("pmid"):
        return a["pmid"] == b["pmid"]
    a_title = (a.get("title") or "").lower()[:60]
    b_title = (b.get("title") or "").lower()[:60]
    return a_title and b_title and a_title == b_title


# ------------------------------------------------------------------ #
# Cross-source fallbacks
# ------------------------------------------------------------------ #
def _crossref_search(
    author: str, year: str, keywords: List[str] | None = None, limit: int = 5
) -> List[Dict[str, Any]]:
    """Search Crossref by author + bibliographic query."""
    query_parts = [author]
    if keywords:
        query_parts.extend(kw.rstrip("*") for kw in keywords[:3])
    query_str = " ".join(query_parts)

    params = {
        "query.bibliographic": query_str,
        "filter": f"from-pub-date:{year},until-pub-date:{year}",
        "rows": str(limit),
        "sort": "relevance",
    }
    url = f"https://api.crossref.org/works?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": f"shawn-bio-search/2.0 (mailto:{os.getenv('CROSSREF_EMAIL', 'user@example.com')})"
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = __import__("json").loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    out = []
    for item in data.get("message", {}).get("items", []):
        authors_raw = item.get("author", [])
        author_names = [
            f"{a.get('family', '')} {a.get('given', '')}" for a in authors_raw
        ]
        pub_year = str(
            item.get("published", {}).get("date-parts", [[0]])[0][0]
        )
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""

        out.append({
            "source": "crossref",
            "pmid": None,
            "title": title,
            "authors": author_names,
            "first_author": authors_raw[0].get("family", "") if authors_raw else "",
            "year": int(pub_year) if pub_year.isdigit() else 0,
            "doi": item.get("DOI", ""),
            "journal": (item.get("container-title") or [""])[0],
            "url": item.get("URL", ""),
            "abstract": item.get("abstract", ""),
            "mesh_terms": [],
            "citations": item.get("is-referenced-by-count", 0),
        })

    return out


def _semantic_scholar_search(
    author: str, year: str, keywords: List[str] | None = None, limit: int = 5
) -> List[Dict[str, Any]]:
    """Search Semantic Scholar by query + year filter.

    Uses proper TLS verification via the shared _http helper.
    """
    from ._http import http_json, build_url

    query_parts = [author]
    if keywords:
        query_parts.extend(kw.rstrip("*") for kw in keywords[:3])
    query_str = " ".join(query_parts)

    params = {
        "query": query_str,
        "year": year,
        "limit": str(limit),
        "fields": "title,authors,year,externalIds,journal,abstract,citationCount,paperId",
    }
    url = build_url("https://api.semanticscholar.org/graph/v1/paper/search", params)

    s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY")
    headers: Dict[str, str] = {}
    if s2_key:
        headers["x-api-key"] = s2_key

    try:
        data = http_json(url, headers=headers, timeout=20)
    except Exception:
        return []

    out = []
    for paper in data.get("data", []):
        ext = paper.get("externalIds") or {}
        authors_raw = paper.get("authors") or []
        journal_info = paper.get("journal") or {}

        out.append({
            "source": "semantic_scholar",
            "pmid": ext.get("PubMed"),
            "title": paper.get("title", ""),
            "authors": [a.get("name", "") for a in authors_raw],
            "first_author": authors_raw[0].get("name", "").split()[-1] if authors_raw else "",
            "year": paper.get("year") or 0,
            "doi": ext.get("DOI", ""),
            "journal": journal_info.get("name", "") if isinstance(journal_info, dict) else "",
            "url": f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}",
            "abstract": paper.get("abstract") or "",
            "mesh_terms": [],
            "citations": paper.get("citationCount", 0),
        })

    return out


def _score_to_confidence(score: float) -> str:
    """Classify confidence level.

    Since base score is 0.35 (author+year match), thresholds are adjusted:
    - HIGH: base + good keyword overlap
    - MEDIUM: base + some overlap (most author+year matches land here)
    - LOW: only partial match
    - UNLIKELY: very low overlap among many candidates (likely wrong person)
    """
    if score >= 0.55:
        return "HIGH"
    elif score >= 0.40:
        return "MEDIUM"
    elif score >= 0.25:
        return "LOW"
    else:
        return "UNLIKELY"


def _build_verification_strategies(
    first_author: str,
    year: str,
    keywords: List[str] | None = None,
) -> List[tuple[str, str]]:
    """Build progressive search strategies from strict to broad.

    Key improvement: keywords are used in pairs (top 2) rather than all at once,
    because AND-ing too many [tiab] terms produces 0 results for niche papers.
    Also generates single-keyword strategies as fallback.
    """
    strategies = []

    # Prepare keyword clauses at different strictness levels
    kw_full = ""   # all keywords (strict)
    kw_pair = ""   # top 2 keywords (balanced)
    kw_single = "" # top 1 keyword (broad)

    if keywords:
        clean_kw = [kw.rstrip("*") + "*" if not kw.endswith("*") and len(kw) > 5
                     else kw for kw in keywords]

        if len(clean_kw) >= 3:
            kw_full = " AND " + " AND ".join(f"{k}[tiab]" for k in clean_kw[:3])
        if len(clean_kw) >= 2:
            kw_pair = " AND " + " AND ".join(f"{k}[tiab]" for k in clean_kw[:2])
        if clean_kw:
            kw_single = f" AND {clean_kw[0]}[tiab]"

    # Strategy 1: 1au + year + all keywords (most strict)
    if kw_full:
        strategies.append(("1au+year+kw_full", f"{first_author}[1au] AND {year}[dp]{kw_full}"))

    # Strategy 2: 1au + year + 2 keywords
    if kw_pair:
        strategies.append(("1au+year+kw_pair", f"{first_author}[1au] AND {year}[dp]{kw_pair}"))

    # Strategy 3: 1au + year + 1 keyword
    if kw_single:
        strategies.append(("1au+year+kw_single", f"{first_author}[1au] AND {year}[dp]{kw_single}"))

    # Strategy 4: 1au + year only
    strategies.append(("1au+year", f"{first_author}[1au] AND {year}[dp]"))

    # Strategy 5: au (any position) + year + 2 keywords
    if kw_pair:
        strategies.append(("au+year+kw_pair", f"{first_author}[au] AND {year}[dp]{kw_pair}"))

    # Strategy 6: au + year + 1 keyword
    if kw_single:
        strategies.append(("au+year+kw_single", f"{first_author}[au] AND {year}[dp]{kw_single}"))

    # Strategy 7: au + year
    strategies.append(("au+year", f"{first_author}[au] AND {year}[dp]"))

    # Strategy 8: au + keywords only (no year — handles year-off-by-one)
    if kw_pair:
        strategies.append(("au+kw_pair", f"{first_author}[au]{kw_pair}"))

    return strategies


# ------------------------------------------------------------------ #
# 4. Advanced field-tag search
# ------------------------------------------------------------------ #
def search_advanced(
    query: str | None = None,
    first_author: str | None = None,
    any_author: str | None = None,
    year: str | None = None,
    year_range: tuple[str, str] | None = None,
    title_words: List[str] | None = None,
    tiab_words: List[str] | None = None,
    mesh_terms: List[str] | None = None,
    doi: str | None = None,
    journal: str | None = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Build a PubMed query using proper field tags.

    This replaces plain-text searching with structured field-tag queries
    that dramatically improve precision for citation verification.
    """
    parts = []

    if query:
        parts.append(query)
    if first_author:
        parts.append(f"{first_author}[1au]")
    if any_author:
        parts.append(f"{any_author}[au]")
    if year:
        parts.append(f"{year}[dp]")
    if year_range:
        parts.append(f"{year_range[0]}:{year_range[1]}[dp]")
    if title_words:
        for tw in title_words:
            parts.append(f"{tw}[ti]")
    if tiab_words:
        for tw in tiab_words:
            parts.append(f"{tw}[tiab]")
    if mesh_terms:
        for mt in mesh_terms:
            parts.append(f"{mt}[MeSH]")
    if doi:
        parts.append(f"{doi}[doi]")
    if journal:
        parts.append(f"{journal}[journal]")

    combined = " AND ".join(parts)
    return _esearch_and_fetch(combined, limit=limit)


# ------------------------------------------------------------------ #
# 5. Original plain-text search (backward compatible)
# ------------------------------------------------------------------ #
def fetch_pubmed(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch papers from PubMed using plain-text query.

    This is the original function, kept for backward compatibility.
    For citation verification, prefer verify_citation() or search_advanced().
    """
    return _esearch_and_fetch(query, limit=limit)


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #
def _esearch_and_fetch(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Run esearch → efetch pipeline."""
    params = _api_params({
        "term": query,
        "retmode": "json",
        "retmax": str(max(1, min(limit, 100))),
    })
    search_url = f"{_base_url()}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = _get_json(search_url)
    ids = data.get("esearchresult", {}).get("idlist", [])

    if not ids:
        return []

    return _fetch_details(ids)


def _fetch_details(ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full metadata + abstracts for a list of PMIDs."""
    # Summary for basic metadata
    sum_params = _api_params({"id": ",".join(ids), "retmode": "json"})
    summary_url = f"{_base_url()}/esummary.fcgi?{urllib.parse.urlencode(sum_params)}"
    summary = _get_json(summary_url).get("result", {})

    # Full XML for abstracts + DOI + MeSH
    fetch_params = _api_params({"id": ",".join(ids), "retmode": "xml"})
    fetch_url = f"{_base_url()}/efetch.fcgi?{urllib.parse.urlencode(fetch_params)}"

    abstract_map: Dict[str, str] = {}
    doi_map: Dict[str, str] = {}
    mesh_map: Dict[str, List[str]] = {}
    author_detail_map: Dict[str, List[Dict[str, str]]] = {}

    try:
        root = _get_xml(fetch_url)
        for art in root.findall(".//PubmedArticle"):
            pid = art.findtext(".//PMID", default="").strip()

            # Abstract
            parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                txt = "".join(ab.itertext()).strip()
                if txt:
                    parts.append(txt)
            if pid and parts:
                abstract_map[pid] = " ".join(parts)

            # DOI from ArticleIdList (more reliable than elocationid)
            doi_el = art.find(".//ArticleIdList/ArticleId[@IdType='doi']")
            if doi_el is not None and doi_el.text:
                doi_map[pid] = doi_el.text.strip()

            # MeSH terms
            mesh_list = []
            for mh in art.findall(".//MeshHeadingList/MeshHeading"):
                desc = mh.findtext("DescriptorName", "")
                if desc:
                    mesh_list.append(desc)
            if mesh_list:
                mesh_map[pid] = mesh_list

            # Detailed author info (LastName, ForeName, Initials, Affiliation)
            authors_detail = []
            for au in art.findall(".//AuthorList/Author"):
                authors_detail.append({
                    "last": au.findtext("LastName", ""),
                    "fore": au.findtext("ForeName", ""),
                    "initials": au.findtext("Initials", ""),
                })
            if authors_detail:
                author_detail_map[pid] = authors_detail
    except Exception:
        pass

    out = []
    for pid in ids:
        doc = summary.get(pid) or {}
        authors = [a.get("name") for a in (doc.get("authors") or []) if a.get("name")]
        elocation = doc.get("elocationid") or ""
        doi_fallback = re.search(r"10\.[^\s;]+", elocation)
        doi = doi_map.get(pid) or (doi_fallback.group(0) if doi_fallback else None)

        out.append({
            "source": "pubmed",
            "id": f"pmid:{pid}",
            "pmid": pid,
            "title": doc.get("title") or "",
            "authors": authors,
            "authors_detail": author_detail_map.get(pid, []),
            "first_author": author_detail_map.get(pid, [{}])[0].get("last", ""),
            "year": int((doc.get("pubdate") or "0")[:4] or 0),
            "doi": doi,
            "journal": doc.get("fulljournalname") or doc.get("source") or "",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": abstract_map.get(pid, ""),
            "mesh_terms": mesh_map.get(pid, []),
            "citations": 0,
        })

    return out
