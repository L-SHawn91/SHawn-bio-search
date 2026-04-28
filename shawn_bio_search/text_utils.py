"""Shared text utilities for tokenization, overlap scoring, and dedup keys.

Centralizes helpers that were previously duplicated across `scoring.py`,
`search.py`, and `scripts/gather_papers.py`. Behavior is preserved bit-for-bit
so existing scoring outputs do not shift.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Set, Tuple


_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,}")

# Biomedical synonym groups: tokens within the same group are treated as equivalent
# during overlap scoring. Keeps overlap_ratio fast (pure token set ops, no ML).
_SYNONYM_GROUPS: List[FrozenSet[str]] = [
    frozenset({"cancer", "carcinoma", "malignancy", "tumor", "tumour", "neoplasm", "neoplasia"}),
    frozenset({"endometrial", "uterine", "endometrium", "uteri", "endometrioid"}),
    frozenset({"mutation", "variant", "alteration", "snp", "polymorphism"}),
    frozenset({"expression", "mrna", "transcript", "transcription", "rna"}),
    frozenset({"protein", "proteomic", "proteome", "peptide", "polypeptide"}),
    frozenset({"receptor", "signaling", "pathway", "signal", "transduction"}),
    frozenset({"proliferation", "growth", "invasion", "migration", "metastasis"}),
    frozenset({"apoptosis", "death", "autophagy", "senescence", "necrosis"}),
    frozenset({"sequencing", "rnaseq", "scrna", "transcriptome", "transcriptomic"}),
    frozenset({"implantation", "receptivity", "decidualization", "decidua", "woi"}),
    frozenset({"organoid", "spheroid", "culture", "vitro"}),
    frozenset({"immune", "immunology", "inflammation", "inflammatory", "cytokine"}),
    frozenset({"hormone", "estrogen", "estradiol", "progesterone", "progestin"}),
    frozenset({"stem", "progenitor", "differentiation", "pluripotent"}),
    frozenset({"methylation", "epigenetic", "chromatin", "histone", "acetylation"}),
    frozenset({"therapy", "treatment", "drug", "chemotherapy", "inhibitor"}),
    frozenset({"analysis", "profiling", "assay", "experiment", "study"}),
]

# Pre-build token→canonical_group_id map for O(1) lookup
_TOKEN_TO_GROUP: Dict[str, int] = {}
for _gid, _grp in enumerate(_SYNONYM_GROUPS):
    for _tok in _grp:
        _TOKEN_TO_GROUP[_tok] = _gid


def tokenize(text: str) -> Set[str]:
    """Return the set of lowercase alphanumeric tokens (length >= 3) in `text`."""
    return set(_TOKEN_RE.findall((text or "").lower()))


def _syn_ids(tokens: Set[str]) -> Set[str]:
    """Return the set of synonym group IDs for the given tokens."""
    return {f"__syn_{_TOKEN_TO_GROUP[t]}__" for t in tokens if t in _TOKEN_TO_GROUP}


def overlap_ratio(base: str, target: str) -> float:
    """Fraction of tokens in `base` that also appear in `target`.

    Synonym-aware: tokens in the same biomedical synonym group count as matching
    (e.g. 'cancer' matches 'carcinoma', 'mutation' matches 'variant').
    Denominator is always len(base_tokens) to preserve the original semantics.
    Returns 0.0 if either side is empty.
    """
    a = tokenize(base)
    b = tokenize(target)
    if not a or not b:
        return 0.0
    # Build matchable set for target: raw tokens + their synonym group IDs
    b_match = b | _syn_ids(b)
    # Count each base token as matching if raw or syn-ID hits target
    matched = sum(
        1 for tok in a
        if tok in b_match
        or (_TOKEN_TO_GROUP.get(tok) is not None
            and f"__syn_{_TOKEN_TO_GROUP[tok]}__" in b_match)
    )
    return matched / len(a)


def dedupe_key(record: Dict[str, Any]) -> Tuple[str, str]:
    """Stable identity key for cross-source dedup: prefer DOI > title > id."""
    title = (record.get("title") or "").strip().lower()
    doi = (record.get("doi") or "").strip().lower()
    pid = (record.get("id") or "").strip().lower()
    if doi:
        return ("doi", doi)
    if title:
        return ("title", title)
    return ("id", pid)


def merge_unique_list(a: Any, b: Any) -> List[Any]:
    """Concatenate two iterables, dropping case-insensitive string duplicates while preserving order."""
    out: List[Any] = []
    seen: Set[str] = set()
    for item in (a or []):
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    for item in (b or []):
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


__all__ = ["tokenize", "overlap_ratio", "dedupe_key", "merge_unique_list"]
