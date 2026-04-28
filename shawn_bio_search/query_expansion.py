"""Query expansion helpers for SHawn-bio-search."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional


_QUERY_SYNONYMS: Dict[str, List[str]] = {
    "endometrium": ["endometrial", "uterus", "uterine"],
    "endometrial": ["endometrium", "uterus", "uterine"],
    "uterus": ["uterine", "endometrium", "endometrial"],
    "uterine": ["uterus", "endometrium", "endometrial"],
    "ovary": ["ovarian", "female reproductive"],
    "ovarian": ["ovary", "female reproductive"],
    "organoid": ["organoids", "3d culture", "3d model"],
    "organoids": ["organoid", "3d culture", "3d model"],
    "implantation": ["embryo implantation", "receptivity"],
    "fibrosis": ["fibrotic", "scarring"],
    "regeneration": ["repair", "regenerative"],
    "repair": ["regeneration", "regenerative"],
    "ivf": ["in vitro fertilization", "assisted reproduction"],
    "adenomyosis": ["uterine adenomyosis"],
    # Cycle / hormone terms
    "progesterone": ["P4", "progestogen", "luteal"],
    "estrogen": ["E2", "oestrogen", "estradiol"],
    "estradiol": ["estrogen", "E2", "oestrogen"],
    # Cancer
    "endometriosis": ["endometriotic", "ectopic endometrium"],
    "cancer": ["carcinoma", "malignancy", "tumor", "tumour"],
    "carcinoma": ["cancer", "malignancy", "adenocarcinoma"],
}

# Domain tokens: expansion is only applied when at least one query token belongs
# to a known biomedical domain.  When *safe=True* and none of the query tokens
# hit this set the query is returned unchanged to avoid cross-domain drift.
_DOMAIN_ANCHOR_TOKENS: frozenset = frozenset(_QUERY_SYNONYMS.keys())


def expand_query(query: str, max_terms: int = 8, safe: bool = False) -> str:
    """Expand a query with lightweight biomedical synonyms.

    Keeps the original query intact and appends a small OR block to improve recall
    without exploding the search into an unreadable boolean wall.

    Args:
        query: The search query string to expand.
        max_terms: Maximum number of synonym terms to append (default 8).
        safe: When ``True``, only expand queries that contain at least one
            token from the known synonym dictionary.  Queries with no
            recognized domain tokens are returned unchanged, preventing
            cross-domain drift (e.g. plant biology, prostate cancer) caused by
            generic OR expansion.  Recommended when using ``--expand-query``
            with narrow biomedical queries.

    Returns:
        Expanded query string, or the original query if no expansions were
        found or if *safe* mode blocked expansion.
    """
    tokens = [t.strip('()[]{}\"\'.,:;').lower() for t in query.split()]
    expansions: List[str] = []
    seen = set()

    # In safe mode, bail out immediately when the query has no recognized
    # domain tokens — returning the original prevents spurious OR blocks.
    if safe and not any(t in _DOMAIN_ANCHOR_TOKENS for t in tokens):
        return query

    for token in tokens:
        for synonym in _QUERY_SYNONYMS.get(token, []):
            if synonym.lower() in seen:
                continue
            seen.add(synonym.lower())
            expansions.append(synonym)
            if len(expansions) >= max_terms:
                break
        if len(expansions) >= max_terms:
            break

    if not expansions:
        return query

    or_terms = " OR ".join(f'"{term}"' if " " in term else term for term in expansions)
    return f"({query}) OR ({or_terms})"


# ---------------------------------------------------------------------------
# ⑫ MeSH term injection (PubMed-only)
# ---------------------------------------------------------------------------

# Pre-built phrase → MeSH heading lookup for common biomedical terms.
# Longer/more-specific phrases are listed first so they match before shorter
# substrings (dict preserves insertion order in Python 3.7+).
_MESH_MAP: Dict[str, str] = {
    "endometrial cancer":         "Endometrial Neoplasms",
    "endometrial carcinoma":      "Endometrial Neoplasms",
    "uterine cancer":             "Endometrial Neoplasms",
    "uterine carcinoma":          "Endometrial Neoplasms",
    "endometrial neoplasm":       "Endometrial Neoplasms",
    "endometriosis":              "Endometriosis",
    "adenomyosis":                "Adenomyosis",
    "embryo implantation":        "Embryo Implantation",
    "uterine receptivity":        "Embryo Implantation",
    "implantation failure":       "Embryo Implantation",
    "recurrent implantation failure": "Embryo Implantation",
    "organoid":                   "Organoids",
    "organoids":                  "Organoids",
    "stem cell":                  "Stem Cells",
    "stem cells":                 "Stem Cells",
    "cell proliferation":         "Cell Proliferation",
    "cell migration":             "Cell Movement",
    "cell invasion":              "Neoplasm Invasiveness",
    "apoptosis":                  "Apoptosis",
    "autophagy":                  "Autophagy",
    "gene expression":            "Gene Expression",
    "rna sequencing":             "Sequence Analysis, RNA",
    "rnaseq":                     "Sequence Analysis, RNA",
    "single cell":                "Single-Cell Analysis",
    "scrna":                      "Single-Cell Analysis",
    "dna methylation":            "DNA Methylation",
    "epigenetics":                "Epigenomics",
    "histone":                    "Histones",
    "chromatin":                  "Chromatin",
    "progesterone":               "Progesterone",
    "estrogen":                   "Estrogens",
    "estradiol":                  "Estradiol",
    "hormone therapy":            "Hormone Replacement Therapy",
    "infertility":                "Infertility, Female",
    "ivf":                        "Fertilization in Vitro",
    "in vitro fertilization":     "Fertilization in Vitro",
    "ovarian cancer":             "Ovarian Neoplasms",
    "breast cancer":              "Breast Neoplasms",
    "cervical cancer":            "Uterine Cervical Neoplasms",
    "mutation":                   "Mutation",
    "variant":                    "Genetic Variation",
    "snp":                        "Polymorphism, Single Nucleotide",
    "copy number":                "DNA Copy Number Variations",
    "microsatellite":             "Microsatellite Instability",
    "mismatch repair":            "DNA Mismatch Repair",
    "immune checkpoint":          "Immune Checkpoint Inhibitors",
    "immunotherapy":              "Immunotherapy",
    "chemotherapy":               "Drug Therapy",
    "targeted therapy":           "Molecular Targeted Therapy",
}

_MESH_NCBI_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def _ncbi_mesh_lookup(term: str, api_key: str = "", timeout: float = 4.0) -> Optional[str]:
    """Query NCBI E-utilities MeSH db for the best matching heading."""
    params = {
        "db": "mesh", "term": term, "retmode": "json", "retmax": "1",
    }
    if api_key:
        params["api_key"] = api_key
    url = f"{_MESH_NCBI_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None
        # Fetch the actual MeSH heading for the first ID
        fetch_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=mesh&id={ids[0]}&retmode=json"
            + (f"&api_key={api_key}" if api_key else "")
        )
        with urllib.request.urlopen(fetch_url, timeout=timeout) as r:
            summary = json.loads(r.read())
        result = summary.get("result", {})
        heading = (
            result.get(ids[0], {}).get("ds_meshterms", [None])[0]
            or result.get(ids[0], {}).get("ds_name", "")
        )
        return heading.strip() or None
    except Exception:
        return None


def mesh_expand_query(
    query: str,
    *,
    api_key: str = "",
    live_lookup: bool = False,
    max_terms: int = 3,
) -> str:
    """Append MeSH terms to a query for improved PubMed recall.

    Uses the pre-built _MESH_MAP first. When *live_lookup=True* and no
    static match is found, queries the NCBI MeSH database (requires network).
    MeSH syntax is PubMed-only; pass the result only to PubMed fetch calls.

    Args:
        query:       Original search query.
        api_key:     NCBI API key (higher rate limit).
        live_lookup: Try NCBI MeSH API when no static match found.
        max_terms:   Maximum MeSH terms to append (default 3).

    Returns:
        Query string with MeSH OR block appended, or original if no match.
    """
    lower = query.lower()
    mesh_terms: List[str] = []
    seen: set = set()

    for phrase, heading in _MESH_MAP.items():
        if len(mesh_terms) >= max_terms:
            break
        if phrase in lower and heading not in seen:
            mesh_terms.append(f'"{heading}"[MeSH Terms]')
            seen.add(heading)

    if not mesh_terms and live_lookup:
        # Try NCBI live lookup for the first 3-word segment of the query
        first_segment = " ".join(query.split()[:3])
        heading = _ncbi_mesh_lookup(first_segment, api_key=api_key or os.getenv("NCBI_API_KEY", ""))
        if heading and heading not in seen:
            mesh_terms.append(f'"{heading}"[MeSH Terms]')

    if not mesh_terms:
        return query

    mesh_block = " OR ".join(mesh_terms)
    return f"({query}) OR ({mesh_block})"
