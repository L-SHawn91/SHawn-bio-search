"""HuggingFace Hub dataset source (no API key required for public datasets).

The HF Hub Datasets API returns ML-oriented datasets including a sizeable
biomedical corpus (`bigbio/*` collection has 100+ ready-to-load BioNLP tasks
— PubMedQA, MedQA, BioASQ, n2c2, MIMIC-derivatives, etc.) that are
otherwise hard to discover from GEO / SRA / OmicsDI alone.

The endpoint is anonymous-friendly. Set HUGGINGFACE_TOKEN (or HF_TOKEN) for
private datasets and gentler rate-limit treatment.

API: https://huggingface.co/docs/hub/api#get-apidatasets
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List, Optional

from ._http import http_json

_BASE = "https://huggingface.co/api/datasets"


def _auth_headers() -> Dict[str, str]:
    token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _year_from_iso(s: Optional[str]) -> Optional[int]:
    if not s or not isinstance(s, str) or len(s) < 4:
        return None
    try:
        return int(s[:4])
    except ValueError:
        return None


def _tags_to_assay(tags: List[str]) -> str:
    """Pick an assay-like signal from HF tags.

    Prefer `task_categories:*` since that is the closest analog to "what kind
    of data is in here". Falls back to `task_ids:*` then the raw first tag.
    """
    if not tags:
        return ""
    for prefix in ("task_categories:", "task_ids:"):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith(prefix):
                return tag.split(":", 1)[1]
    return ""


def _tags_to_organism(tags: List[str]) -> str:
    """HF rarely encodes organism explicitly; surface anything matching the
    common bio biome tags so a downstream filter can still pick it up."""
    if not tags:
        return ""
    bio_markers = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        lower = tag.lower()
        if any(token in lower for token in ("human", "mouse", "rat", "drosophila", "zebrafish", "yeast")):
            bio_markers.append(tag)
    return ", ".join(bio_markers)


def _truncate(text: Optional[str], limit: int = 600) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def fetch_huggingface_datasets(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search HF Hub for datasets matching `query`.

    Returns normalized records using the same shape as the other dataset
    sources in `scripts/dataset_search.py` (`repository`, `accession`,
    `title`, `organism`, `assay`, `summary`, `url`, ...).
    """
    if not query or not query.strip():
        return []

    params = {
        "search": query,
        "limit": str(limit),
        "full": "true",
    }
    url = f"{_BASE}?{urllib.parse.urlencode(params)}"

    try:
        rows = http_json(url, headers=_auth_headers())
    except Exception:
        return []

    if not isinstance(rows, list):
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ds_id = row.get("id") or row.get("modelId") or ""
        if not ds_id:
            continue
        tags = row.get("tags") or []
        card = row.get("cardData") or {}
        pretty = card.get("pretty_name") if isinstance(card, dict) else None
        description = (
            (isinstance(card, dict) and card.get("description"))
            or row.get("description")
            or ""
        )
        out.append({
            "repository": "huggingface",
            "accession": ds_id,
            "title": pretty or ds_id,
            "organism": _tags_to_organism(tags),
            "assay": _tags_to_assay(tags),
            "sample_count": None,
            "disease": "",
            "tissue": "",
            "summary": _truncate(description),
            "year": _year_from_iso(row.get("lastModified") or row.get("createdAt")),
            "raw_available": True,
            "processed_available": True,
            "downloads": int(row.get("downloads") or 0),
            "likes": int(row.get("likes") or 0),
            "url": f"https://huggingface.co/datasets/{ds_id}",
        })
    return out
