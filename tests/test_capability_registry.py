"""Tests for the seed capability registry shape and metadata."""

from __future__ import annotations

import os

import pytest

from shawn_bio_search.orchestrator import (
    Capability,
    SourceStep,
    capabilities,
    clear_registry,
    get,
    list_capabilities,
    missing_required_keys,
    register,
)
from shawn_bio_search.sources import KEYED_SOURCES


def _reseed():
    clear_registry()
    capabilities._install_seed_capabilities()


def test_seed_capabilities_present():
    _reseed()
    names = list_capabilities()
    assert "paper.by_keywords" in names
    assert "paper.by_doi" in names


def test_paper_by_keywords_chain_order_and_sources():
    _reseed()
    cap = get("paper.by_keywords")
    expected = ["pubmed", "europe_pmc", "openalex", "arxiv", "biorxiv", "medrxiv"]
    assert [step.source for step in cap.chain] == expected
    for step in cap.chain:
        assert isinstance(step, SourceStep)
        assert step.why  # every step has a justification


def test_paper_by_doi_chain_starts_with_crossref():
    _reseed()
    cap = get("paper.by_doi")
    assert cap.chain[0].source == "crossref"
    assert "DOI" in cap.chain[0].why or "doi" in cap.chain[0].why.lower()


def test_capability_must_have_chain():
    with pytest.raises(ValueError):
        Capability(name="x.empty", chain=())


def test_register_rejects_duplicate_without_replace():
    _reseed()
    cap = get("paper.by_keywords")
    with pytest.raises(ValueError):
        register(cap)


def test_register_replace_overwrites():
    _reseed()
    fake = Capability(
        name="paper.by_keywords",
        chain=(SourceStep("pubmed", lambda args: [], why="stub"),),
    )
    register(fake, replace=True)
    assert get("paper.by_keywords") is fake


def test_get_unknown_capability_raises():
    _reseed()
    with pytest.raises(KeyError):
        get("nonexistent.cap")


def test_default_success_predicate_treats_nonempty_as_sufficient():
    _reseed()
    cap = get("paper.by_keywords")
    assert cap.success_predicate([{"id": 1}], {"query": "x"}) is True
    assert cap.success_predicate([], {"query": "x"}) is False


def test_missing_required_keys_for_free_source_is_empty():
    assert missing_required_keys("pubmed") == ()
    assert missing_required_keys("openalex") == ()


def test_missing_required_keys_when_env_unset(monkeypatch):
    # Ensure scopus env is unset so the function reports the missing key.
    for var in KEYED_SOURCES.get("scopus", []):
        monkeypatch.delenv(var, raising=False)
    assert missing_required_keys("scopus") == tuple(KEYED_SOURCES["scopus"])


def test_missing_required_keys_when_any_env_set(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "test-token")
    assert missing_required_keys("core") == ()


def test_missing_required_keys_for_unknown_source():
    assert missing_required_keys("not-a-real-source") == ()
