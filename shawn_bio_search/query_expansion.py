"""Query expansion helpers for SHawn-bio-search."""

from typing import Dict, List


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
