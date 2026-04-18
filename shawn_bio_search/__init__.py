"""
Shawn-Bio-Search: Multi-source biomedical literature search with claim-level evidence scoring.

A unified interface for searching biomedical literature across multiple sources:
- PubMed (NCBI)
- Scopus (Elsevier, requires API key)
- Google Scholar (via SerpAPI)
- Europe PMC
- OpenAlex
- Crossref
- ClinicalTrials.gov
- bioRxiv
- medRxiv
- Semantic Scholar
- arXiv (q-bio)
- OpenAIRE
- CORE (requires API key)
- Unpaywall
- F1000Research
- DOAJ

Example:
    >>> from shawn_bio_search import search_papers
    >>> results = search_papers(
    ...     query="organoid stem cell",
    ...     claim="ECM is essential for organoid formation",
    ...     max_results=10
    ... )
"""

__version__ = "0.1.1"
__author__ = "SHawn-bio-search contributors"

from .search import search_papers, SearchResult
from .sources import ALL_SOURCES, FREE_SOURCES, KEYED_SOURCES, check_sources
from .env import load_dotenv

__all__ = [
    "search_papers",
    "SearchResult",
    "ALL_SOURCES",
    "FREE_SOURCES",
    "KEYED_SOURCES",
    "check_sources",
    "load_dotenv",
]
