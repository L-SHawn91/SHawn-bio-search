"""Project-aware search presets for SHawn-bio-search."""

from typing import Dict


_PROJECT_PRESETS: Dict[str, Dict[str, str]] = {
    "endometrial-organoid-review": {
        "query_suffix": "(endometrial OR endometrium OR uterine) AND (organoid OR organoids OR assembloid)",
        "claim_hint": "Focus on endometrial organoid biology, comparative models, methods, and translational evidence.",
    },
    "regenerative-screening": {
        "query_suffix": "(regeneration OR repair OR fibrosis) AND (endometrium OR uterine OR ovary OR ovarian)",
        "claim_hint": "Focus on regenerative candidates with female reproductive relevance and cross-organ evidence.",
    },
    "adenomyosis": {
        "query_suffix": "(adenomyosis) AND (fertility OR implantation OR IVF OR endometrium)",
        "claim_hint": "Focus on mechanistic, clinical, and fertility-outcome evidence for adenomyosis.",
    },
    "implantation": {
        "query_suffix": "(implantation OR receptivity OR trophoblast) AND (endometrium OR uterine)",
        "claim_hint": "Focus on implantation interface, receptivity, trophoblast, and endometrial signaling.",
    },
}


def apply_project_preset(query: str, claim: str = "", project_mode: str = "") -> Dict[str, str]:
    """Return effective query/claim after applying a project preset."""
    if not project_mode:
        return {
            "original_query": query,
            "effective_query": query,
            "original_claim": claim,
            "effective_claim": claim,
            "project_mode": "",
        }

    preset = _PROJECT_PRESETS.get(project_mode)
    if not preset:
        return {
            "original_query": query,
            "effective_query": query,
            "original_claim": claim,
            "effective_claim": claim,
            "project_mode": project_mode,
        }

    effective_query = f"({query}) AND {preset['query_suffix']}"
    effective_claim = claim.strip()
    if not effective_claim:
        effective_claim = preset["claim_hint"]

    return {
        "original_query": query,
        "effective_query": effective_query,
        "original_claim": claim,
        "effective_claim": effective_claim,
        "project_mode": project_mode,
    }
