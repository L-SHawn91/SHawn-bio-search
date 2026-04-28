"""Offline unit tests for crossref source: fetch_crossref_by_doi, lookup_ids_by_doi.

All HTTP calls are monkeypatched — no network required. Covers:
- DOI normalizer correctness (regex prefix strip, not lstrip char-set)
- lookup_ids_by_doi happy path (Crossref + NCBI both respond)
- lookup_ids_by_doi graceful degradation (Crossref fails, NCBI missing)
- fetch_crossref_by_doi normalizer
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from shawn_bio_search.sources.crossref import fetch_crossref_by_doi, lookup_ids_by_doi


# ---------------------------------------------------------------------------
# Helpers — fake HTTP responses
# ---------------------------------------------------------------------------

def _crossref_response(doi: str = "10.1038/ncb3516") -> dict:
    return {
        "message": {
            "DOI": doi,
            "URL": f"http://dx.doi.org/{doi}",
            "title": ["Test paper title"],
            "author": [{"given": "A", "family": "Author"}],
            "issued": {"date-parts": [[2017]]},
            "container-title": ["Nature Cell Biology"],
            "is-referenced-by-count": 42,
            "abstract": "<p>Test abstract.</p>",
        }
    }


def _ncbi_response(pmid: str = "29203885", pmcid: str = "PMC6789") -> dict:
    return {"records": [{"pmid": pmid, "pmcid": pmcid}]}


def _mock_get_json(crossref_data=None, ncbi_data=None, crossref_raises=False):
    """Return a side_effect function that dispatches by URL."""
    def _impl(url: str):
        if "crossref.org" in url:
            if crossref_raises:
                raise urllib.error.URLError("mock crossref failure")
            return crossref_data or _crossref_response()
        if "ncbi.nlm.nih.gov" in url:
            return ncbi_data or _ncbi_response()
        raise AssertionError(f"unexpected URL in test: {url}")
    return _impl


# ---------------------------------------------------------------------------
# DOI normalizer — lookup_ids_by_doi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_doi, expected_clean", [
    ("10.1038/ncb3516",                        "10.1038/ncb3516"),
    ("https://doi.org/10.1038/ncb3516",        "10.1038/ncb3516"),
    ("http://doi.org/10.1038/ncb3516",         "10.1038/ncb3516"),
    ("https://dx.doi.org/10.1038/ncb3516",     "10.1038/ncb3516"),
    ("http://dx.doi.org/10.1038/ncb3516",      "10.1038/ncb3516"),
    # lstrip bug would have stripped leading '1' from "10." if chars matched
    ("https://doi.org/10.1016/j.stem.2025.07.005", "10.1016/j.stem.2025.07.005"),
])
def test_doi_normalizer_strips_prefix_correctly(raw_doi, expected_clean):
    """Regex prefix strip must not eat DOI chars (lstrip char-set bug)."""
    with patch(
        "shawn_bio_search.sources.crossref._get_json",
        side_effect=_mock_get_json(
            crossref_data=_crossref_response(expected_clean),
            ncbi_data={"records": []},
        ),
    ):
        result = lookup_ids_by_doi(raw_doi)
    assert result.get("doi") == expected_clean, (
        f"DOI normalizer produced wrong clean from {raw_doi!r}: {result.get('doi')!r}"
    )


# ---------------------------------------------------------------------------
# lookup_ids_by_doi — happy path
# ---------------------------------------------------------------------------

def test_lookup_ids_by_doi_returns_doi_pmid_pmcid():
    with patch(
        "shawn_bio_search.sources.crossref._get_json",
        side_effect=_mock_get_json(),
    ):
        result = lookup_ids_by_doi("10.1038/ncb3516")
    assert result["doi"] == "10.1038/ncb3516"
    assert result["pmid"] == "29203885"
    assert result["pmcid"] == "PMC6789"
    assert "url" in result


def test_lookup_ids_by_doi_empty_input():
    result = lookup_ids_by_doi("")
    assert result == {}


def test_lookup_ids_by_doi_none_input():
    result = lookup_ids_by_doi(None)  # type: ignore[arg-type]
    assert result == {}


# ---------------------------------------------------------------------------
# lookup_ids_by_doi — degraded paths
# ---------------------------------------------------------------------------

def test_lookup_ids_by_doi_crossref_failure_returns_best_effort_doi():
    """Crossref failure should not raise; best-effort doi key preserved."""
    with patch(
        "shawn_bio_search.sources.crossref._get_json",
        side_effect=_mock_get_json(crossref_raises=True, ncbi_data={"records": []}),
    ):
        result = lookup_ids_by_doi("10.1038/ncb3516")
    assert result.get("doi") == "10.1038/ncb3516"
    assert "pmid" not in result


def test_lookup_ids_by_doi_ncbi_no_records():
    """NCBI returning empty records list → no pmid/pmcid, no crash."""
    with patch(
        "shawn_bio_search.sources.crossref._get_json",
        side_effect=_mock_get_json(ncbi_data={"records": []}),
    ):
        result = lookup_ids_by_doi("10.1038/ncb3516")
    assert result["doi"] == "10.1038/ncb3516"
    assert "pmid" not in result
    assert "pmcid" not in result


def test_lookup_ids_by_doi_ncbi_record_missing_pmid():
    """NCBI record present but pmid key absent → no pmid key in result."""
    with patch(
        "shawn_bio_search.sources.crossref._get_json",
        side_effect=_mock_get_json(ncbi_data={"records": [{"pmcid": "PMC999"}]}),
    ):
        result = lookup_ids_by_doi("10.1038/ncb3516")
    assert "pmid" not in result
    assert result.get("pmcid") == "PMC999"


# ---------------------------------------------------------------------------
# fetch_crossref_by_doi — normalizer also fixed
# ---------------------------------------------------------------------------

def test_fetch_crossref_by_doi_normalizes_https_prefix():
    with patch(
        "shawn_bio_search.sources.crossref._get_json",
        return_value=_crossref_response("10.1038/ncb3516"),
    ) as mock_get:
        result = fetch_crossref_by_doi("https://doi.org/10.1038/ncb3516")
    # The URL sent to Crossref must NOT include the https://doi.org/ prefix
    called_url = mock_get.call_args[0][0]
    assert "10.1038" in called_url
    assert "https://doi.org" not in called_url
    assert result is not None
    assert result["doi"] == "10.1038/ncb3516"
