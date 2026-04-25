"""SciVal source module (requires API key and entitlement)."""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


BASE_URL = "https://api.elsevier.com/metrics/metrics"


def _get_json(url: str, headers: Dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def fetch_scival_author_metrics(
    author_ids: List[str],
    metrics: Optional[List[str]] = None,
    year_range: str = "5yrs",
    include_self_citations: bool = True,
    by_year: bool = True,
    included_docs: str = "AllPublicationTypes",
) -> Dict[str, Any]:
    """Fetch SciVal author metrics for one or more Scopus author IDs.

    Returns an empty dict if API credentials/entitlements are unavailable.
    """
    api_key = os.getenv("SCIVAL_API_KEY") or os.getenv("SCOPUS_API_KEY")
    if not api_key or not author_ids:
        return {}

    metrics = metrics or [
        "ScholarlyOutput",
        "CitationsPerPublication",
        "FieldWeightedCitationImpact",
        "ViewsCount",
        "FieldWeightedViewsImpact",
        "ScholarlyOutput",
    ]

    params = {
        "authors": ",".join(str(x).strip() for x in author_ids if str(x).strip()),
        "metrics": ",".join(metrics),
        "yearRange": year_range,
        "includeSelfCitations": str(include_self_citations).lower(),
        "byYear": str(by_year).lower(),
        "includedDocs": included_docs,
        "journalImpactType": "CiteScore",
        "showAsFieldWeighted": "true",
        "indexType": "hIndex",
        "httpAccept": "application/json",
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}

    inst = os.getenv("SCIVAL_INSTTOKEN") or os.getenv("SCOPUS_INSTTOKEN")
    if inst:
        headers["X-ELS-Insttoken"] = inst

    try:
        data = _get_json(url, headers)
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}
