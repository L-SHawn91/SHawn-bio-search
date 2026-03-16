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
}


def expand_query(query: str, max_terms: int = 8) -> str:
    """Expand a query with lightweight biomedical synonyms.

    Keeps the original query intact and appends a small OR block to improve recall
    without exploding the search into an unreadable boolean wall.
    """
    tokens = [t.strip('()[]{}\"\'.,:;').lower() for t in query.split()]
    expansions: List[str] = []
    seen = set()

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
