"""Shared text utilities for tokenization, overlap scoring, and dedup keys.

Centralizes helpers that were previously duplicated across `scoring.py`,
`search.py`, and `scripts/gather_papers.py`. Behavior is preserved bit-for-bit
so existing scoring outputs do not shift.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple


_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,}")


def tokenize(text: str) -> Set[str]:
    """Return the set of lowercase alphanumeric tokens (length >= 3) in `text`."""
    return set(_TOKEN_RE.findall((text or "").lower()))


def overlap_ratio(base: str, target: str) -> float:
    """Fraction of tokens in `base` that also appear in `target` (0.0 if either side empty)."""
    a = tokenize(base)
    b = tokenize(target)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


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
