"""Source modules for biomedical literature search."""

import os
from typing import Dict, List

from .pubmed import fetch_pubmed
from .europe_pmc import fetch_europe_pmc
from .openalex import fetch_openalex
from .crossref import fetch_crossref
from .clinicaltrials import fetch_clinicaltrials
from .biorxiv import fetch_biorxiv
from .medrxiv import fetch_medrxiv
from .scopus import fetch_scopus
from .google_scholar import fetch_google_scholar
from .semanticscholar import fetch_semanticscholar
from .arxiv import fetch_arxiv
from .openaire import fetch_openaire
from .core import fetch_core
from .unpaywall import fetch_unpaywall, fetch_unpaywall_by_doi
from .f1000research import fetch_f1000research
from .doaj import fetch_doaj

# Sources that work with no API key at all.
FREE_SOURCES = [
    "pubmed",
    "europe_pmc",
    "openalex",
    "crossref",
    "clinicaltrials",
    "biorxiv",
    "medrxiv",
    "semantic_scholar",  # key optional, works without
    "arxiv",
    "openaire",
    "f1000research",
    "doaj",
]

# Sources that require a key (or practical-identity email) to return results.
# Each value lists env vars whose presence (any of them) enables the source.
KEYED_SOURCES: Dict[str, List[str]] = {
    "scopus": ["SCOPUS_API_KEY"],
    "google_scholar": ["SERPAPI_API_KEY"],
    "core": ["CORE_API_KEY"],
    "unpaywall": ["UNPAYWALL_EMAIL", "CROSSREF_EMAIL"],
}

ALL_SOURCES = FREE_SOURCES + list(KEYED_SOURCES.keys())


def check_sources() -> Dict[str, Dict[str, object]]:
    """Report which sources are ready to use in the current environment.

    Returns a dict keyed by source name with `ready` (bool), `needs`
    (missing env var names, if any), and `note` (human-readable hint).
    """
    report: Dict[str, Dict[str, object]] = {}

    free_notes = {
        "pubmed": "NCBI_API_KEY optional, raises rate limit",
        "semantic_scholar": "SEMANTIC_SCHOLAR_API_KEY or S2_API_KEY optional",
        "crossref": "CROSSREF_EMAIL optional (polite pool)",
        "openalex": "CROSSREF_EMAIL/mailto optional (polite pool)",
    }
    for name in FREE_SOURCES:
        report[name] = {
            "ready": True,
            "needs": [],
            "note": free_notes.get(name, "no key required"),
        }

    for name, env_vars in KEYED_SOURCES.items():
        configured = [v for v in env_vars if os.getenv(v)]
        report[name] = {
            "ready": bool(configured),
            "needs": [] if configured else env_vars,
            "note": (
                f"configured via {configured[0]}"
                if configured
                else f"set one of: {', '.join(env_vars)}"
            ),
        }

    return report


__all__ = [
    "fetch_pubmed",
    "fetch_europe_pmc",
    "fetch_openalex",
    "fetch_crossref",
    "fetch_clinicaltrials",
    "fetch_biorxiv",
    "fetch_medrxiv",
    "fetch_semanticscholar",
    "fetch_scopus",
    "fetch_google_scholar",
    "fetch_arxiv",
    "fetch_openaire",
    "fetch_core",
    "fetch_unpaywall",
    "fetch_unpaywall_by_doi",
    "fetch_f1000research",
    "fetch_doaj",
    "ALL_SOURCES",
    "FREE_SOURCES",
    "KEYED_SOURCES",
    "check_sources",
]
