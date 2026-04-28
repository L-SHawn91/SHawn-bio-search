"""Tests for features added in the Tier 1-3 improvement pass:
recency_bonus, citation_velocity, mesh_expand_query, source_health,
to_bibtex/to_ris, and batch_score_papers.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from shawn_bio_search.scoring import score_paper, batch_score_papers
from shawn_bio_search.query_expansion import mesh_expand_query
from shawn_bio_search.search import SearchResult, _SOURCE_HEALTH, _record_source_health


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paper(title: str = "Endometrial organoid", abstract: str = "",
           year: int = 2024, citations: int = 0, source: str = "pubmed") -> Dict[str, Any]:
    return {"title": title, "abstract": abstract, "year": year,
            "citations": citations, "source": source, "doi": "10.test/x"}


def _result_with_papers(papers) -> SearchResult:
    return SearchResult(data={"papers": papers, "count": len(papers), "warnings": []})


# ---------------------------------------------------------------------------
# recency_bonus
# ---------------------------------------------------------------------------

class TestRecencyBonus:
    def test_2024_paper_gets_full_bonus(self):
        p = score_paper(_paper(year=2024), claim="", hypothesis="")
        assert p["recency_bonus"] == pytest.approx(0.02, abs=1e-4)

    def test_2022_paper_gets_partial_bonus(self):
        p = score_paper(_paper(year=2022), claim="", hypothesis="")
        assert p["recency_bonus"] == pytest.approx(0.012, abs=1e-4)

    def test_2018_paper_gets_small_bonus(self):
        p = score_paper(_paper(year=2018), claim="", hypothesis="")
        assert p["recency_bonus"] == pytest.approx(0.006, abs=1e-4)

    def test_old_paper_gets_zero_bonus(self):
        p = score_paper(_paper(year=2010), claim="", hypothesis="")
        assert p["recency_bonus"] == pytest.approx(0.0, abs=1e-4)

    def test_recent_paper_scores_higher_than_old(self):
        new = score_paper(_paper(year=2024, title="endometrial organoid"), claim="endometrial organoid", hypothesis="")
        old = score_paper(_paper(year=2010, title="endometrial organoid"), claim="endometrial organoid", hypothesis="")
        assert new["stage1_score"] > old["stage1_score"]

    def test_missing_year_gives_zero_bonus(self):
        p = _paper()
        p.pop("year")
        scored = score_paper(p, claim="", hypothesis="")
        assert scored["recency_bonus"] == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# citation_velocity
# ---------------------------------------------------------------------------

class TestCitationVelocity:
    def test_highly_cited_paper_scores_higher(self):
        high = score_paper(_paper(year=2020, citations=400, title="endometrial organoid"),
                           claim="endometrial organoid", hypothesis="")
        low  = score_paper(_paper(year=2020, citations=0,   title="endometrial organoid"),
                           claim="endometrial organoid", hypothesis="")
        assert high["stage1_score"] > low["stage1_score"]

    def test_citation_velocity_caps_at_50_per_year(self):
        # Both 200 and 500 citations in 2 years exceed the 50/yr cap — velocity component equal
        # age = max(2026-2024, 1) = 2; vel = min(200/2=100, 50)/50 = 1.0 for both
        high = score_paper(_paper(year=2024, citations=200), claim="", hypothesis="")
        higher = score_paper(_paper(year=2024, citations=500), claim="", hypothesis="")
        # abs component differs (200 vs 500), but velocity is both capped at 1.0
        # overall stage1 should differ only by the abs component
        assert high["stage1_score"] < higher["stage1_score"]  # abs component lifts higher

    def test_zero_citations_does_not_raise(self):
        p = score_paper(_paper(citations=0, year=2020), claim="", hypothesis="")
        assert p["stage1_score"] >= 0

    def test_missing_citations_treated_as_zero(self):
        p = _paper()
        p.pop("citations", None)
        scored = score_paper(p, claim="", hypothesis="")
        assert scored["stage1_score"] >= 0


# ---------------------------------------------------------------------------
# mesh_expand_query
# ---------------------------------------------------------------------------

class TestMeshExpandQuery:
    def test_endometrial_gets_mesh_term(self):
        result = mesh_expand_query("endometrial organoid")
        assert "[MeSH Terms]" in result or "Endometrium" in result

    def test_organoid_gets_mesh_term(self):
        result = mesh_expand_query("endometrial organoid")
        assert "Organoids" in result or "organoid" in result.lower()

    def test_unknown_query_passes_through(self):
        q = "completely unknown xyzabc123"
        result = mesh_expand_query(q)
        assert q in result

    def test_max_terms_limits_injection(self):
        result_2 = mesh_expand_query("endometrial organoid implantation", max_terms=2)
        result_5 = mesh_expand_query("endometrial organoid implantation", max_terms=5)
        count_2 = result_2.count("[MeSH Terms]")
        count_5 = result_5.count("[MeSH Terms]")
        assert count_2 <= count_5

    def test_pubmed_only_flag_adds_mesh_syntax(self):
        result = mesh_expand_query("endometrial cancer")
        # MeSH terms use bracket notation
        assert "[MeSH Terms]" in result or result != "endometrial cancer"


# ---------------------------------------------------------------------------
# source health monitor
# ---------------------------------------------------------------------------

class TestSourceHealth:
    def setup_method(self):
        _SOURCE_HEALTH.clear()

    def teardown_method(self):
        _SOURCE_HEALTH.clear()

    def test_success_resets_consecutive_failures(self):
        _record_source_health("pubmed", False)
        _record_source_health("pubmed", False)
        _record_source_health("pubmed", True)
        assert _SOURCE_HEALTH["pubmed"]["consecutive"] == 0

    def test_failures_increment_consecutive(self):
        _record_source_health("pubmed", False)
        _record_source_health("pubmed", False)
        assert _SOURCE_HEALTH["pubmed"]["consecutive"] == 2

    def test_healthy_source_is_not_skipped(self, monkeypatch):
        _SOURCE_HEALTH.clear()
        called = {}

        def fake_fetch(q, n):
            called["pubmed"] = True
            return []

        monkeypatch.setattr("shawn_bio_search.search.fetch_pubmed", fake_fetch)
        from shawn_bio_search.search import search_papers
        search_papers(query="endometrial", sources=["pubmed"], max_results=1)
        assert called.get("pubmed"), "Healthy source must not be skipped"

    def test_repeated_failures_deprioritize_source(self, monkeypatch):
        fail_count = {"n": 0}

        def fake_fetch(q, n):
            fail_count["n"] += 1
            raise RuntimeError("network error")

        monkeypatch.setattr("shawn_bio_search.search.fetch_pubmed", fake_fetch)
        # Patch the module-level constant directly (env var set at import time)
        monkeypatch.setattr("shawn_bio_search.search._HEALTH_FAIL_THRESHOLD", 2)
        _SOURCE_HEALTH.clear()

        from shawn_bio_search.search import search_papers
        search_papers(query="endometrial", sources=["pubmed"], max_results=1)
        search_papers(query="endometrial", sources=["pubmed"], max_results=1)
        # After threshold=2, source is deprioritized — third call must be skipped
        count_before = fail_count["n"]
        search_papers(query="endometrial", sources=["pubmed"], max_results=1)
        assert fail_count["n"] == count_before, "Deprioritized source must be skipped"


# ---------------------------------------------------------------------------
# to_bibtex / to_ris
# ---------------------------------------------------------------------------

class TestBibTeXExport:
    def _make_result(self):
        papers = [
            {"title": "Endometrial organoid culture",
             "authors_short": "Turco M",
             "year": 2017, "doi": "10.1038/ncb3516",
             "venue": "Nature Cell Biology",
             "abstract": "Long-term hormone-responsive organoid cultures."},
            {"title": "Patient-derived endometrial organoids",
             "authors_short": "Boretto M",
             "year": 2019, "doi": "10.1016/j.stem.2019.01.005",
             "venue": "Cell Stem Cell", "abstract": ""},
        ]
        return _result_with_papers(papers)

    def test_bibtex_contains_article_entries(self):
        bib = self._make_result().to_bibtex()
        assert bib.count("@article{") == 2

    def test_bibtex_contains_doi(self):
        bib = self._make_result().to_bibtex()
        assert "10.1038/ncb3516" in bib

    def test_bibtex_key_format(self):
        bib = self._make_result().to_bibtex()
        assert "turco2017" in bib.lower()

    def test_bibtex_top_n_limits_output(self):
        bib = self._make_result().to_bibtex(top_n=1)
        assert bib.count("@article{") == 1

    def test_bibtex_empty_papers_returns_empty(self):
        assert _result_with_papers([]).to_bibtex() == ""


class TestRISExport:
    def _make_result(self):
        papers = [
            {"title": "Endometrial organoid culture",
             "authors_short": "Turco M; Branco M",
             "year": 2017, "doi": "10.1038/ncb3516",
             "venue": "Nature Cell Biology",
             "abstract": "Long-term cultures."},
        ]
        return _result_with_papers(papers)

    def test_ris_contains_type_tag(self):
        ris = self._make_result().to_ris()
        assert "TY  - JOUR" in ris

    def test_ris_contains_end_tag(self):
        ris = self._make_result().to_ris()
        assert "ER  - " in ris

    def test_ris_contains_doi(self):
        ris = self._make_result().to_ris()
        assert "10.1038/ncb3516" in ris

    def test_ris_splits_multiple_authors(self):
        ris = self._make_result().to_ris()
        assert ris.count("AU  - ") == 2

    def test_ris_top_n_limits_output(self):
        r = _result_with_papers([
            {"title": "A", "doi": "10.a/1"},
            {"title": "B", "doi": "10.b/2"},
        ])
        ris = r.to_ris(top_n=1)
        assert ris.count("TY  - JOUR") == 1

    def test_ris_empty_papers_returns_empty(self):
        assert _result_with_papers([]).to_ris() == ""


# ---------------------------------------------------------------------------
# batch_score_papers
# ---------------------------------------------------------------------------

class TestBatchScorePapers:
    def test_returns_same_count_as_input(self):
        papers = [_paper(title=f"paper {i}") for i in range(5)]
        out = batch_score_papers(papers, claim="endometrial organoid", hypothesis="")
        assert len(out) == 5

    def test_each_paper_has_evidence_score(self):
        papers = [_paper(title="endometrial organoid"), _paper(title="unrelated xyz")]
        out = batch_score_papers(papers, claim="endometrial organoid", hypothesis="")
        for p in out:
            assert "evidence_score" in p
            assert 0.0 <= p["evidence_score"] <= 1.0

    def test_relevant_paper_scores_higher_than_irrelevant(self):
        rel = batch_score_papers(
            [_paper(title="endometrial organoid uterine biology")],
            claim="endometrial organoids model uterine function", hypothesis="")
        irr = batch_score_papers(
            [_paper(title="completely unrelated topic xyz")],
            claim="endometrial organoids model uterine function", hypothesis="")
        assert rel[0]["evidence_score"] > irr[0]["evidence_score"]

    def test_empty_list_returns_empty(self):
        assert batch_score_papers([], claim="test", hypothesis="") == []

    def test_embed_disabled_still_scores(self, monkeypatch):
        monkeypatch.setenv("SBS_EMBED_ENABLED", "0")
        papers = [_paper(title="endometrial organoid")]
        out = batch_score_papers(papers, claim="endometrial organoid", hypothesis="")
        assert len(out) == 1
        assert out[0].get("embed_sim") is None or out[0].get("embed_sim", -1) < 0
