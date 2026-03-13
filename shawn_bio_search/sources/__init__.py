"""Source modules for biomedical literature search."""

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

ALL_SOURCES = [
    "pubmed",
    "europe_pmc", 
    "openalex",
    "crossref",
    "clinicaltrials",
    "biorxiv",
    "medrxiv",
    "semantic_scholar",
    "scopus",
    "google_scholar",
]

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
    "ALL_SOURCES",
]
