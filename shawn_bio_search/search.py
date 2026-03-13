"""Core search functionality for Shawn-Bio-Search."""

import json
import os
from typing import Any, Dict, List, Optional

from .sources.pubmed import fetch_pubmed
from .sources.europe_pmc import fetch_europe_pmc
from .sources.openalex import fetch_openalex
from .sources.crossref import fetch_crossref
from .sources.clinicaltrials import fetch_clinicaltrials
from .sources.biorxiv import fetch_biorxiv
from .sources.medrxiv import fetch_medrxiv
from .sources.semanticscholar import fetch_semanticscholar

# Optional sources (require API keys)
from .sources.scopus import fetch_scopus
from .sources.google_scholar import fetch_google_scholar

from .scoring import score_paper
from .formatter import format_results


class SearchResult:
    """Container for search results."""
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.count = data.get("count", 0)
        self.papers = data.get("papers", [])
        self.warnings = data.get("warnings", [])
    
    def to_json(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)
    
    def to_plain(self, top_n: int = 10) -> str:
        return format_results(self.papers, fmt="plain", top_n=top_n)
    
    def to_markdown(self, top_n: int = 10) -> str:
        return format_results(self.papers, fmt="markdown", top_n=top_n)


def search_papers(
    query: str,
    claim: str = "",
    hypothesis: str = "",
    max_results: int = 10,
    sources: Optional[List[str]] = None,
) -> SearchResult:
    """Search papers across multiple sources.
    
    Args:
        query: Search query string
        claim: Optional claim to verify (enables claim-level scoring)
        hypothesis: Optional hypothesis to test
        max_results: Maximum results per source
        sources: List of sources to search (None = all available)
    
    Returns:
        SearchResult object containing papers and metadata
    
    Example:
        >>> results = search_papers(
        ...     query="organoid stem cell niche",
        ...     claim="ECM is essential for organoid formation"
        ... )
        >>> print(results.to_plain())
    """
    all_sources = {
        "pubmed": fetch_pubmed,
        "europe_pmc": fetch_europe_pmc,
        "openalex": fetch_openalex,
        "crossref": fetch_crossref,
        "clinicaltrials": fetch_clinicaltrials,
        "biorxiv": fetch_biorxiv,
        "medrxiv": fetch_medrxiv,
        "semantic_scholar": fetch_semanticscholar,
        "scopus": fetch_scopus,
        "google_scholar": fetch_google_scholar,
    }
    
    if sources is None:
        sources = list(all_sources.keys())
    
    papers = []
    warnings = []
    
    for source_name in sources:
        if source_name not in all_sources:
            warnings.append(f"Unknown source: {source_name}")
            continue
        
        fetch_func = all_sources[source_name]
        try:
            results = fetch_func(query, max_results)
            if not results and source_name in ["scopus", "google_scholar", "semantic_scholar"]:
                if source_name == "semantic_scholar":
                    if not (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY")):
                        warnings.append("semantic_scholar skipped: API key not set")
                else:
                    api_key_var = f"{source_name.upper()}_API_KEY"
                    if not os.getenv(api_key_var) and not os.getenv(f"{source_name.upper().replace('_', '')}_API_KEY"):
                        warnings.append(f"{source_name} skipped: API key not set")
            papers.extend(results)
        except Exception as e:
            warnings.append(f"{source_name} failed: {e}")
    
    # Deduplicate
    papers = _dedupe_papers(papers)
    
    # Score papers
    if claim or hypothesis:
        papers = [score_paper(p, claim, hypothesis) for p in papers]
        papers.sort(key=lambda x: x.get("evidence_score", 0), reverse=True)
    
    data = {
        "query": query,
        "claim": claim,
        "hypothesis": hypothesis,
        "count": len(papers),
        "warnings": warnings,
        "papers": papers,
    }
    
    return SearchResult(data)


def _dedupe_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate papers based on DOI or title."""
    seen = set()
    out = []
    for p in papers:
        title = (p.get("title") or "").strip().lower()
        doi = (p.get("doi") or "").strip().lower()
        pid = (p.get("id") or "").strip().lower()
        key = (doi, title) if (doi or title) else ("", pid)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
