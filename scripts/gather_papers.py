#!/usr/bin/env python3
"""Multi-source paper retrieval for evidence and hypothesis workflows.

Global sources (public API + key-based where needed):
- PubMed (Entrez)
- Scopus (Elsevier API)
- Google Scholar (SerpAPI)
- Europe PMC
- OpenAlex
- Crossref
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shawn_bio_search.text_utils import (  # noqa: E402
    dedupe_key as _dedupe_key,
    merge_unique_list as _merge_unique_list,
    overlap_ratio as _overlap_ratio,
    tokenize as _tokenize,
)


def _get_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    cleaned = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if len(p.strip()) >= 30]


_NEG_TERMS = {
    "not",
    "no",
    "without",
    "lack",
    "lacks",
    "failed",
    "fail",
    "fails",
    "reduced",
    "decrease",
    "decreased",
    "lower",
    "suppressed",
    "inhibit",
    "inhibited",
    "inhibits",
}


def _claim_is_negative(claim: str) -> bool:
    toks = _tokenize(claim)
    return any(t in _NEG_TERMS for t in toks)


def _sentence_stage2(claim: str, hypothesis: str, text: str) -> Dict[str, Any]:
    sentences = _split_sentences(text)
    if not claim or not sentences:
        return {
            "support_score": 0.0,
            "contradiction_score": 0.0,
            "best_support_sentence": "",
            "best_contradict_sentence": "",
            "hypothesis_sentence_overlap": 0.0,
            "stage2_score": 0.0,
        }

    claim_neg = _claim_is_negative(claim)
    best_support = (0.0, "")
    best_contra = (0.0, "")
    best_hyp = 0.0

    for s in sentences:
        ov = _overlap_ratio(claim, s)
        hov = _overlap_ratio(hypothesis, s) if hypothesis else 0.0
        stoks = _tokenize(s)
        has_neg = any(t in _NEG_TERMS for t in stoks)

        support = ov
        contra = 0.0
        if claim_neg:
            # If claim is itself negative, non-negative sentence can contradict it.
            if not has_neg:
                contra = ov * 0.85
        else:
            if has_neg:
                contra = ov * 0.85

        if support > best_support[0]:
            best_support = (support, s)
        if contra > best_contra[0]:
            best_contra = (contra, s)
        if hov > best_hyp:
            best_hyp = hov

    stage2 = max(0.0, best_support[0] - 0.7 * best_contra[0] + 0.25 * best_hyp)
    return {
        "support_score": round(best_support[0], 4),
        "contradiction_score": round(best_contra[0], 4),
        "best_support_sentence": best_support[1],
        "best_contradict_sentence": best_contra[1],
        "hypothesis_sentence_overlap": round(best_hyp, 4),
        "stage2_score": round(min(stage2, 1.0), 4),
    }


def _score(p: Dict[str, Any], claim: str, hypothesis: str) -> Dict[str, Any]:
    text = f"{p.get('title', '')} {p.get('abstract', '')}".strip()
    claim_overlap = _overlap_ratio(claim, text) if claim else 0.0
    hypothesis_overlap = _overlap_ratio(hypothesis, text) if hypothesis else 0.0

    citations = p.get("citations") or 0
    if isinstance(citations, str) and citations.isdigit():
        citations = int(citations)
    if not isinstance(citations, int):
        citations = 0

    source = (p.get("source") or "").strip().lower()
    source_weight_map = {
        "pubmed": 1.0,
        "europe_pmc": 0.96,
        "openalex": 0.95,
        "semantic_scholar": 0.98,
        "crossref": 0.9,
        "scopus": 0.97,
        "google_scholar": 0.82,
        "clinicaltrials": 0.9,
        "biorxiv": 0.84,
        "medrxiv": 0.84,
    }
    source_weight = source_weight_map.get(source, 0.88)
    has_doi = bool((p.get("doi") or "").strip())
    has_abstract = bool((p.get("abstract") or "").strip())
    metadata_bonus = 0.03 * float(has_doi) + 0.04 * float(has_abstract)

    cite_component = min(citations, 500) / 500.0
    stage1_raw = 0.50 * claim_overlap + 0.20 * hypothesis_overlap + 0.20 * cite_component + 0.10 * source_weight + metadata_bonus
    stage1 = round(min(stage1_raw, 1.0), 4)
    s2 = _sentence_stage2(claim, hypothesis, p.get("abstract") or "")
    # 2-stage blend: stage2 gets higher weight when claim exists and abstract is present.
    if claim and has_abstract:
        evidence_score = round(min(0.40 * stage1 + 0.60 * s2["stage2_score"], 1.0), 4)
    else:
        evidence_score = stage1

    p["claim_overlap"] = round(claim_overlap, 4)
    p["hypothesis_overlap"] = round(hypothesis_overlap, 4)
    p["source_weight"] = round(source_weight, 4)
    p["metadata_bonus"] = round(metadata_bonus, 4)
    p["stage1_score"] = stage1
    p["stage2_score"] = s2["stage2_score"]
    p["support_score"] = s2["support_score"]
    p["contradiction_score"] = s2["contradiction_score"]
    p["best_support_sentence"] = s2["best_support_sentence"]
    p["best_contradict_sentence"] = s2["best_contradict_sentence"]
    p["hypothesis_sentence_overlap"] = s2["hypothesis_sentence_overlap"]
    p["evidence_score"] = evidence_score
    return p


def fetch_pubmed(query: str, limit: int) -> List[Dict[str, Any]]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(limit),
        "sort": "relevance",
    }
    key = os.getenv("NCBI_API_KEY")
    if key:
        params["api_key"] = key

    search_url = f"{base}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    search_data = _get_json(search_url)
    ids = search_data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    sum_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
    if key:
        sum_params["api_key"] = key
    summary_url = f"{base}/esummary.fcgi?{urllib.parse.urlencode(sum_params)}"
    summary = _get_json(summary_url).get("result", {})
    fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    if key:
        fetch_params["api_key"] = key
    fetch_url = f"{base}/efetch.fcgi?{urllib.parse.urlencode(fetch_params)}"
    abstract_map: Dict[str, str] = {}
    try:
        xml_text = urllib.request.urlopen(fetch_url, timeout=30).read().decode("utf-8", "ignore")
        root = ET.fromstring(xml_text)
        for art in root.findall(".//PubmedArticle"):
            pid = art.findtext(".//PMID", default="").strip()
            parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                txt = "".join(ab.itertext()).strip()
                if txt:
                    parts.append(txt)
            if pid and parts:
                abstract_map[pid] = " ".join(parts)
    except Exception:
        pass

    out = []
    for pid in ids:
        doc = summary.get(pid) or {}
        authors = [a.get("name") for a in (doc.get("authors") or []) if a.get("name")]
        elocation = doc.get("elocationid") or ""
        doi_match = re.search(r"10\.[^\s;]+", elocation)
        out.append(
            {
                "source": "pubmed",
                "id": f"pmid:{pid}",
                "title": doc.get("title") or "",
                "authors": authors,
                "year": int((doc.get("pubdate") or "0")[:4] or 0),
                "doi": doi_match.group(0) if doi_match else None,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                "abstract": abstract_map.get(pid, ""),
                "citations": 0,
            }
        )
    return out


def fetch_scopus(query: str, limit: int) -> List[Dict[str, Any]]:
    api_key = os.getenv("SCOPUS_API_KEY")
    if not api_key:
        return []

    url = (
        "https://api.elsevier.com/content/search/scopus?"
        + urllib.parse.urlencode({"query": query, "count": str(limit), "sort": "-citedby-count"})
    )
    headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}
    inst = os.getenv("SCOPUS_INSTTOKEN")
    if inst:
        headers["X-ELS-Insttoken"] = inst

    data = _get_json(url, headers=headers)
    entries = data.get("search-results", {}).get("entry", [])

    out = []
    for e in entries:
        creator = e.get("dc:creator")
        out.append(
            {
                "source": "scopus",
                "id": e.get("dc:identifier") or "",
                "title": e.get("dc:title") or "",
                "authors": [creator] if creator else [],
                "year": int((e.get("prism:coverDate") or "0")[:4] or 0),
                "doi": e.get("prism:doi"),
                "url": e.get("prism:url") or "",
                "abstract": "",
                "citations": int(e.get("citedby-count") or 0),
            }
        )
    return out


def fetch_scholar_serpapi(query: str, limit: int) -> List[Dict[str, Any]]:
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
    data = _get_json(url)

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
        out.append(
            {
                "source": "google_scholar",
                "id": str(item.get("result_id") or ""),
                "title": item.get("title") or "",
                "authors": authors,
                "year": int(pub.get("year") or 0),
                "doi": None,
                "url": item.get("link") or "",
                "abstract": item.get("snippet") or "",
                "citations": int((item.get("inline_links") or {}).get("cited_by", {}).get("total") or 0),
            }
        )
    return out


def fetch_europe_pmc(query: str, limit: int) -> List[Dict[str, Any]]:
    params = {"query": query, "format": "json", "pageSize": str(max(1, min(limit, 100)))}
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
        out.append(
            {
                "source": "europe_pmc",
                "id": pid,
                "title": r.get("title") or "",
                "authors": authors,
                "year": year,
                "doi": doi,
                "url": f"https://europepmc.org/article/{(r.get('source') or '').lower()}/{pid}" if pid else "",
                "abstract": r.get("abstractText") or "",
                "citations": int(r.get("citedByCount") or 0),
            }
        )
    return out


def _openalex_abstract(inv: Any) -> str:
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
        out.append(
            {
                "source": "openalex",
                "id": r.get("id") or "",
                "title": r.get("display_name") or r.get("title") or "",
                "authors": authors,
                "year": int(r.get("publication_year") or 0),
                "doi": doi,
                "url": (r.get("primary_location") or {}).get("landing_page_url") or (r.get("id") or ""),
                "abstract": _openalex_abstract(r.get("abstract_inverted_index")),
                "citations": int(r.get("cited_by_count") or 0),
            }
        )
    return out


def fetch_semanticscholar(query: str, limit: int) -> List[Dict[str, Any]]:
    from shawn_bio_search.sources.semanticscholar import fetch_semanticscholar as _fetch
    return _fetch(query, limit)


def fetch_biorxiv(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch preprints from bioRxiv (no API key required).
    
    Note: bioRxiv API doesn't support direct text search.
    We fetch recent papers and filter by query terms locally.
    API docs: https://api.biorxiv.org/
    """
    import time
    
    # Get papers from last 2 years (bioRxiv has no text search API)
    end_date = "2030-12-31"
    start_date = "2023-01-01"
    cursor = 0
    batch_size = 100
    
    all_papers = []
    query_terms = _tokenize(query)
    
    # Try up to 3 batches to find enough matching papers
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
                authors_list = item.get("authors", "")
                
                # Filter by query relevance
                content = (title + " " + abstract).lower()
                if not any(term in content for term in query_terms):
                    continue
                
                # Parse authors
                authors = []
                if authors_list:
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
            time.sleep(1.1)  # Rate limit: 1 request per second
            
        except Exception:
            break
    
    return all_papers[:limit]


def fetch_medrxiv(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch preprints from medRxiv (no API key required).
    
    Shares same API structure as bioRxiv but separate server.
    Note: No direct text search, fetch and filter locally.
    """
    import time
    
    end_date = "2030-12-31"
    start_date = "2023-01-01"
    cursor = 0
    batch_size = 100
    
    all_papers = []
    query_terms = _tokenize(query)
    
    for _ in range(3):
        if len(all_papers) >= limit * 3:
            break
            
        url = f"https://api.medrxiv.org/pubs/{start_date}/{end_date}/{cursor}/{batch_size}"
        
        try:
            data = _get_json(url)
            collection = data.get("collection", [])
            
            if not collection:
                break
            
            for item in collection:
                title = item.get("title", "")
                abstract = item.get("abstract", "")
                authors_list = item.get("authors", "")
                
                # Filter by query
                content = (title + " " + abstract).lower()
                if not any(term in content for term in query_terms):
                    continue
                
                authors = []
                if authors_list:
                    authors = [a.strip() for a in authors_list.split(",") if a.strip()][:10]
                
                doi = item.get("doi", "")
                medrxiv_url = item.get("medrxiv_url", "")
                url_link = f"https://www.medrxiv.org/content/{doi}" if doi else medrxiv_url
                
                all_papers.append({
                    "source": "medrxiv",
                    "id": doi or medrxiv_url,
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


def fetch_clinicaltrials(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch clinical trials from ClinicalTrials.gov (no API key required).
    
    API v2 docs: https://clinicaltrials.gov/data-api/api
    """
    # Use the v2 API with filter syntax
    params = {
        "query.term": query,
        "pageSize": str(max(1, min(limit, 100))),
        "fields": "NCTId,ProtocolSection,DerivedSection",
    }
    url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(params)
    
    try:
        data = _get_json(url)
    except Exception:
        return []
    
    studies = data.get("studies", [])
    out = []
    
    for study in studies[:limit]:
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        description = protocol.get("descriptionModule", {})
        status = protocol.get("statusModule", {})
        sponsor = protocol.get("sponsorCollaboratorsModule", {})
        
        nct_id = identification.get("nctId", "")
        title = identification.get("briefTitle", "")
        official_title = identification.get("officialTitle", "")
        
        # Get brief summary as abstract
        brief_summary = description.get("briefSummary", "")
        detailed_description = description.get("detailedDescription", "")
        abstract = brief_summary or detailed_description or ""
        
        # Get dates
        start_date = status.get("startDateStruct", {}).get("date", "")
        year = int((start_date or "0000")[:4] or 0) if start_date else 0
        
        # Get lead sponsor
        lead_sponsor = sponsor.get("leadSponsor", {}).get("name", "")
        
        out.append({
            "source": "clinicaltrials",
            "id": nct_id,
            "title": title or official_title,
            "authors": [lead_sponsor] if lead_sponsor else [],  # Sponsor as "author"
            "year": year,
            "doi": None,  # Clinical trials don't have DOIs
            "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
            "abstract": abstract,
            "citations": 0,  # Not applicable for trials
        })
    
    return out


def fetch_crossref(query: str, limit: int) -> List[Dict[str, Any]]:
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
        abs_text = re.sub(r"<[^>]+>", " ", html.unescape(abs_raw)).strip() if abs_raw else ""
        out.append(
            {
                "source": "crossref",
                "id": doi or r.get("URL") or "",
                "title": title_list[0] if title_list else "",
                "authors": authors,
                "year": year,
                "doi": doi,
                "url": r.get("URL") or "",
                "abstract": re.sub(r"\s+", " ", abs_text),
                "citations": int(r.get("is-referenced-by-count") or 0),
            }
        )
    return out


def _author_variants(name: str) -> List[tuple[str, str, str]]:
    raw = (name or "").strip()
    if not raw:
        return []
    cleaned = raw.replace(".", " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return []

    variants: List[tuple[str, str, str]] = []

    def build_variant(family: str, given: str) -> None:
        family = (family or "").strip()
        given = (given or "").strip()
        if not family:
            return
        family_key = family.lower()
        given_tokens = [t for t in given.split() if t]
        initials = "".join(t[0].lower() for t in given_tokens if t)
        canonical = f"{given} {family}".strip() if given else family
        item = (family_key, initials, canonical)
        if item not in variants:
            variants.append(item)

    if "," in cleaned:
        family, given = [x.strip() for x in cleaned.split(",", 1)]
        build_variant(family, given)
        return variants

    parts = cleaned.split()
    if len(parts) == 1:
        build_variant(parts[0], "")
        return variants

    if len(parts) == 2:
        left, right = parts
        if len(right) == 1 and len(left) > 1:
            build_variant(left, right)
            build_variant(right, left)
            return variants
        if len(left) == 1 and len(right) > 1:
            build_variant(right, left)
            build_variant(left, right)
            return variants

    build_variant(parts[-1], " ".join(parts[:-1]))
    if len(parts) == 2:
        build_variant(parts[0], parts[1])

    return variants


def _best_author_label(labels: List[str]) -> str:
    if not labels:
        return ""
    labels = [x.strip() for x in labels if x and x.strip()]
    if not labels:
        return ""
    labels.sort(key=lambda s: (
        any(len(tok) > 1 for tok in s.replace('.', ' ').split()),
        len(s),
    ), reverse=True)
    return labels[0]


def _merge_authors(a: Any, b: Any) -> List[str]:
    merged: Dict[tuple[str, str], List[str]] = {}
    order: List[tuple[str, str]] = []

    for item in list(a or []) + list(b or []):
        if not item:
            continue
        label = str(item).strip().replace('.', '')
        if not label:
            continue
        variants = _author_variants(label)
        if not variants:
            continue

        chosen_key = None
        for family_key, initials, _canonical in variants:
            key = (family_key, initials)
            if key in merged:
                chosen_key = key
                break

        if chosen_key is None:
            family_key, initials, _canonical = variants[0]
            chosen_key = (family_key, initials)
            merged[chosen_key] = []
            order.append(chosen_key)

        merged[chosen_key].append(label)

    return [_best_author_label(merged[k]) for k in order]


def _merge_paper_records(base: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)

    merged["source_hits"] = _merge_unique_list(
        base.get("source_hits") or [base.get("source")],
        new.get("source_hits") or [new.get("source")],
    )
    merged["source_ids"] = _merge_unique_list(
        base.get("source_ids") or [base.get("id")],
        new.get("source_ids") or [new.get("id")],
    )
    merged["authors"] = _merge_authors(base.get("authors"), new.get("authors"))

    for field in ["doi", "pmid", "pmcid", "url", "title", "id", "source"]:
        if not merged.get(field) and new.get(field):
            merged[field] = new.get(field)

    if not merged.get("abstract") and new.get("abstract"):
        merged["abstract"] = new.get("abstract")
    elif len((new.get("abstract") or "").strip()) > len((merged.get("abstract") or "").strip()):
        merged["abstract"] = new.get("abstract")

    try:
        merged["year"] = max(int(base.get("year") or 0), int(new.get("year") or 0)) or (base.get("year") or new.get("year"))
    except Exception:
        merged["year"] = base.get("year") or new.get("year")

    try:
        merged["citations"] = max(int(base.get("citations") or 0), int(new.get("citations") or 0))
    except Exception:
        merged["citations"] = base.get("citations") or new.get("citations") or 0

    return merged


def dedupe_by_title_doi(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    order: List[tuple[str, str]] = []
    for p in papers:
        key = _dedupe_key(p)
        if key not in merged:
            item = dict(p)
            item["source_hits"] = item.get("source_hits") or ([item.get("source")] if item.get("source") else [])
            item["source_ids"] = item.get("source_ids") or ([item.get("id")] if item.get("id") else [])
            merged[key] = item
            order.append(key)
        else:
            merged[key] = _merge_paper_records(merged[key], p)
    return [merged[k] for k in order]


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieve papers from global sources")
    parser.add_argument("--query", required=True)
    parser.add_argument("--claim", default="")
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--max-per-source", type=int, default=20)
    parser.add_argument("--no-pubmed", action="store_true")
    parser.add_argument("--no-scopus", action="store_true")
    parser.add_argument("--no-scholar", action="store_true")
    parser.add_argument("--no-europepmc", action="store_true")
    parser.add_argument("--no-openalex", action="store_true")
    parser.add_argument("--no-crossref", action="store_true")
    parser.add_argument("--no-biorxiv", action="store_true")
    parser.add_argument("--no-medrxiv", action="store_true")
    parser.add_argument("--no-clinicaltrials", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    papers: List[Dict[str, Any]] = []
    warnings: List[str] = []

    if not args.no_pubmed:
        try:
            papers.extend(fetch_pubmed(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"pubmed failed: {exc}")

    if not args.no_scopus:
        try:
            got = fetch_scopus(args.query, args.max_per_source)
            if not got and not os.getenv("SCOPUS_API_KEY"):
                warnings.append("scopus skipped: SCOPUS_API_KEY not set")
            papers.extend(got)
        except Exception as exc:
            warnings.append(f"scopus failed: {exc}")

    if not args.no_scholar:
        try:
            got = fetch_scholar_serpapi(args.query, args.max_per_source)
            if not got and not os.getenv("SERPAPI_API_KEY"):
                warnings.append("google_scholar skipped: SERPAPI_API_KEY not set")
            papers.extend(got)
        except Exception as exc:
            warnings.append(f"google_scholar failed: {exc}")

    if not args.no_europepmc:
        try:
            papers.extend(fetch_europe_pmc(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"europe_pmc failed: {exc}")

    if not args.no_openalex:
        try:
            papers.extend(fetch_openalex(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"openalex failed: {exc}")

    if not args.no_crossref:
        try:
            papers.extend(fetch_crossref(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"crossref failed: {exc}")

    # API key not required sources (newly added)
    if not args.no_biorxiv:
        try:
            papers.extend(fetch_biorxiv(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"biorxiv failed: {exc}")

    if not args.no_medrxiv:
        try:
            papers.extend(fetch_medrxiv(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"medrxiv failed: {exc}")

    if not args.no_clinicaltrials:
        try:
            papers.extend(fetch_clinicaltrials(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"clinicaltrials failed: {exc}")

    papers = dedupe_by_title_doi(papers)
    scored = [_score(p, args.claim, args.hypothesis) for p in papers]
    scored.sort(key=lambda x: x.get("evidence_score", 0), reverse=True)

    result = {
        "query": args.query,
        "claim": args.claim,
        "hypothesis": args.hypothesis,
        "count": len(scored),
        "warnings": warnings,
        "papers": scored,
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"saved: {args.out}")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
