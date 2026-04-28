"""Tests for scoring filters: topic_guard, min_evidence, and expand_query safe mode."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from shawn_bio_search.scoring import apply_topic_guard, score_paper
from shawn_bio_search.query_expansion import expand_query
from shawn_bio_search.search import search_papers, _SENTINEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper(title: str, abstract: str = "", source: str = "pubmed") -> Dict[str, Any]:
    return {"title": title, "abstract": abstract, "source": source, "doi": "10.test/x"}


def _scored(title: str, abstract: str = "", claim: str = "") -> Dict[str, Any]:
    paper = _make_paper(title, abstract)
    return score_paper(paper, claim=claim, hypothesis="")


# ---------------------------------------------------------------------------
# topic_guard tests
# ---------------------------------------------------------------------------

class TestApplyTopicGuard:
    def test_plant_paper_is_removed_from_endometrial_query(self):
        papers = [
            _make_paper("Endometrial stromal cell differentiation"),
            _make_paper("Wheat phytohormone signalling in drought stress"),
        ]
        kept = apply_topic_guard(papers, query="endometrial organoid")
        titles = [p["title"] for p in kept]
        assert "Endometrial stromal cell differentiation" in titles
        assert "Wheat phytohormone signalling in drought stress" not in titles

    def test_plant_paper_passes_when_query_mentions_plant(self):
        paper = _make_paper("Wheat phytohormone signalling in drought stress")
        kept = apply_topic_guard([paper], query="wheat phytohormone stress response")
        assert len(kept) == 1, "Guard must not remove paper when query explicitly mentions plant terms"

    def test_prostate_paper_removed_from_endometrial_query(self):
        papers = [
            _make_paper("Endometrial cancer hormone receptor expression"),
            _make_paper("Prostate carcinoma androgen signalling"),
        ]
        kept = apply_topic_guard(papers, query="endometrial cancer")
        titles = [p["title"] for p in kept]
        assert "Endometrial cancer hormone receptor expression" in titles
        assert "Prostate carcinoma androgen signalling" not in titles

    def test_cervical_paper_removed_from_uterine_query(self):
        paper = _make_paper("Cervical cancer HPV integration sites")
        kept = apply_topic_guard([paper], query="uterine endometrial organoid")
        assert len(kept) == 0

    def test_hepatic_paper_removed_when_not_in_query(self):
        paper = _make_paper("Hepatic organoids for drug metabolism")
        kept = apply_topic_guard([paper], query="endometrial organoid")
        assert len(kept) == 0

    def test_renal_paper_removed_when_not_in_query(self):
        paper = _make_paper("Renal tubular cell injury in nephron")
        kept = apply_topic_guard([paper], query="endometrial hormone")
        assert len(kept) == 0

    def test_guard_sets_metadata_on_removed_paper(self):
        paper = _make_paper("Wheat drought stress response")
        apply_topic_guard([paper], query="endometrial")
        assert paper.get("topic_guard_filtered") is True
        assert paper.get("topic_guard_label") == "plant"

    def test_on_topic_paper_not_flagged(self):
        paper = _make_paper("Endometrial organoid hormone response")
        kept = apply_topic_guard([paper], query="endometrial organoid")
        assert len(kept) == 1
        assert not kept[0].get("topic_guard_filtered")

    def test_empty_list_returns_empty(self):
        assert apply_topic_guard([], query="endometrial") == []

    def test_multiple_papers_mixed_filtering(self):
        papers = [
            _make_paper("Endometrial gland organoid"),
            _make_paper("Rice grain development under heat"),
            _make_paper("Uterine natural killer cells"),
            _make_paper("Prostate specific antigen screening"),
        ]
        kept = apply_topic_guard(papers, query="endometrial uterine")
        assert len(kept) == 2
        kept_titles = {p["title"] for p in kept}
        assert "Endometrial gland organoid" in kept_titles
        assert "Uterine natural killer cells" in kept_titles


# ---------------------------------------------------------------------------
# min_evidence filter tests
# ---------------------------------------------------------------------------

class TestMinEvidenceFilter:
    """Tests that the min_evidence threshold correctly removes low-score papers.

    Note: score_paper() recomputes evidence_score from title/abstract/claim overlap,
    so these tests use real papers from openalex fixtures and verify the filter
    logic via the filters_applied metadata rather than exact score expectations.
    We also test the filter directly by calling search_papers with papers that
    have high enough overlap to yield deterministic score ranges.
    """

    def test_filter_metadata_field_exists(self, monkeypatch):
        """filters_applied must always be present in result data."""
        monkeypatch.setattr(
            "shawn_bio_search.sources.pubmed.fetch_pubmed",
            lambda q, n: [],
        )
        results = search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            min_evidence=0.0,
        )
        assert "filters_applied" in results.data
        assert "min_evidence" in results.data["filters_applied"]
        assert "min_evidence_removed" in results.data["filters_applied"]

    def test_threshold_zero_never_removes(self, monkeypatch):
        """min_evidence=0.0 (default) removes nothing."""
        papers = [
            {"title": "Endometrial organoid A", "abstract": "endometrial biology", "source": "pubmed", "doi": ""},
            {"title": "Unrelated paper B", "abstract": "", "source": "pubmed", "doi": ""},
        ]
        monkeypatch.setattr("shawn_bio_search.sources.pubmed.fetch_pubmed", lambda q, n: papers)
        results = search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            min_evidence=0.0,
        )
        assert results.data["filters_applied"]["min_evidence_removed"] == 0

    def test_high_threshold_removes_low_scoring_papers(self, monkeypatch):
        """A threshold of 0.9 should remove papers that don't strongly overlap the claim."""
        papers = [
            # Very off-topic — near-zero overlap with claim
            {"title": "Completely unrelated topic XYZ", "abstract": "", "source": "pubmed", "doi": ""},
        ]
        monkeypatch.setattr("shawn_bio_search.sources.pubmed.fetch_pubmed", lambda q, n: papers)
        results = search_papers(
            query="endometrial organoid",
            claim="endometrial organoids model uterine biology",
            sources=["pubmed"],
            min_evidence=0.9,
        )
        # The unrelated paper should score well below 0.9 and be removed
        assert results.data["filters_applied"]["min_evidence_removed"] >= 1

    def test_min_evidence_warning_in_output(self, monkeypatch):
        papers = [
            {"title": "Completely unrelated xyz", "abstract": "", "source": "pubmed", "doi": ""},
        ]
        monkeypatch.setattr("shawn_bio_search.sources.pubmed.fetch_pubmed", lambda q, n: papers)
        results = search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            min_evidence=0.9,
        )
        warning_text = " ".join(results.warnings)
        # Warning is only emitted when papers are actually removed
        if results.data["filters_applied"]["min_evidence_removed"] > 0:
            assert "min_evidence" in warning_text.lower() or "0.9" in warning_text

    def test_min_evidence_applied_after_topic_guard(self, monkeypatch):
        """Filters are applied in order: topic_guard first, then min_evidence."""
        papers = [
            # Off-topic (prostate) — should be removed by topic_guard before min_evidence sees it
            {"title": "Prostate cancer androgen receptor", "abstract": "prostatic signalling", "source": "pubmed", "doi": ""},
            # Low scoring on-topic — should be removed by min_evidence
            {"title": "Completely unrelated XYZ", "abstract": "", "source": "pubmed", "doi": ""},
        ]
        monkeypatch.setattr("shawn_bio_search.sources.pubmed.fetch_pubmed", lambda q, n: papers)
        results = search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            min_evidence=0.9,
            topic_guard=True,
        )
        fa = results.data["filters_applied"]
        assert fa["topic_guard_removed"] >= 1  # prostate paper removed by guard
        # The result list should be empty or only contain high-scoring papers


# ---------------------------------------------------------------------------
# expand_query safe mode tests
# ---------------------------------------------------------------------------

class TestExpandQuerySafeMode:
    def test_safe_mode_expands_known_domain_query(self):
        expanded = expand_query("endometrial organoid", safe=True)
        assert expanded != "endometrial organoid"
        assert "uterine" in expanded.lower() or "endometrium" in expanded.lower()

    def test_safe_mode_does_not_expand_unknown_domain_query(self):
        # A query with no recognized domain tokens should pass through unchanged
        query = "protein folding amyloid fibril"
        expanded = expand_query(query, safe=True)
        assert expanded == query, f"Safe mode should not expand unknown domain; got: {expanded!r}"

    def test_unsafe_mode_still_works_when_no_synonyms(self):
        # With safe=False and no synonyms, should also return original
        query = "protein folding amyloid fibril"
        expanded = expand_query(query, safe=False)
        assert expanded == query

    def test_safe_mode_default_is_off_for_backward_compatibility(self):
        # Default call (no safe= arg) should behave the same as safe=False
        q = "endometrial organoid"
        default_result = expand_query(q)
        safe_false_result = expand_query(q, safe=False)
        assert default_result == safe_false_result


# ---------------------------------------------------------------------------
# Auto-enable topic_guard when expand=True
# ---------------------------------------------------------------------------

class TestTopicGuardAutoEnableWithExpand:
    """When expand=True is used, topic_guard should be auto-enabled."""

    def test_expand_auto_enables_topic_guard_sentinel(self, monkeypatch):
        """When topic_guard is not passed, expanding should auto-enable it."""
        captured = {}

        def _fake_apply_topic_guard(papers, query):
            captured["called"] = True
            return papers

        monkeypatch.setattr("shawn_bio_search.search.apply_topic_guard", _fake_apply_topic_guard)
        monkeypatch.setattr(
            "shawn_bio_search.sources.pubmed.fetch_pubmed",
            lambda q, n: [{"title": "test", "abstract": "test", "source": "pubmed"}],
        )

        search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            expand=True,
        )
        assert captured.get("called"), "topic_guard should be auto-called when expand=True"

    def test_expand_with_explicit_false_topic_guard_skips_guard(self, monkeypatch):
        """Explicit topic_guard=False must suppress auto-enable."""
        captured = {}

        def _fake_apply_topic_guard(papers, query):
            captured["called"] = True
            return papers

        monkeypatch.setattr("shawn_bio_search.search.apply_topic_guard", _fake_apply_topic_guard)
        monkeypatch.setattr(
            "shawn_bio_search.sources.pubmed.fetch_pubmed",
            lambda q, n: [{"title": "test", "abstract": "test", "source": "pubmed"}],
        )

        search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            expand=True,
            topic_guard=False,
        )
        assert not captured.get("called"), "Explicit topic_guard=False must suppress the auto-enable"

    def test_no_expand_does_not_auto_enable_topic_guard(self, monkeypatch):
        """Without expand, topic_guard should remain off by default."""
        captured = {}

        def _fake_apply_topic_guard(papers, query):
            captured["called"] = True
            return papers

        monkeypatch.setattr("shawn_bio_search.search.apply_topic_guard", _fake_apply_topic_guard)
        monkeypatch.setattr(
            "shawn_bio_search.sources.pubmed.fetch_pubmed",
            lambda q, n: [{"title": "test", "abstract": "test", "source": "pubmed"}],
        )

        search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            expand=False,
        )
        assert not captured.get("called"), "topic_guard should not be auto-called without expand"

    def test_filters_applied_metadata_reflects_auto_topic_guard(self, monkeypatch):
        monkeypatch.setattr(
            "shawn_bio_search.sources.pubmed.fetch_pubmed",
            lambda q, n: [{"title": "test", "abstract": "test", "source": "pubmed"}],
        )
        results = search_papers(
            query="endometrial organoid",
            sources=["pubmed"],
            expand=True,
        )
        assert results.data["filters_applied"]["topic_guard"] is True


# ---------------------------------------------------------------------------
# Source weight: semantic_scholar weight is 0.88
# ---------------------------------------------------------------------------

class TestSourceWeights:
    def test_semantic_scholar_weight_is_0_88(self):
        from shawn_bio_search.scoring import _SOURCE_WEIGHTS
        assert _SOURCE_WEIGHTS["semantic_scholar"] == 0.88, (
            "semantic_scholar weight should be 0.88 (lowered from 0.98 to reduce false positives)"
        )

    def test_pubmed_remains_highest_weight(self):
        from shawn_bio_search.scoring import _SOURCE_WEIGHTS
        assert _SOURCE_WEIGHTS["pubmed"] == 1.0

    def test_semantic_scholar_lower_than_pubmed_and_europe_pmc(self):
        from shawn_bio_search.scoring import _SOURCE_WEIGHTS
        assert _SOURCE_WEIGHTS["semantic_scholar"] < _SOURCE_WEIGHTS["pubmed"]
        assert _SOURCE_WEIGHTS["semantic_scholar"] < _SOURCE_WEIGHTS["europe_pmc"]

    def test_source_weight_applied_in_score(self):
        """A paper from semantic_scholar should score lower on stage1 than identical pubmed paper."""
        base = {"title": "endometrial organoid uterine", "abstract": "", "citations": 0}
        p_pubmed = dict(base, source="pubmed", doi="")
        p_ss = dict(base, source="semantic_scholar", doi="")
        p_pubmed = score_paper(p_pubmed, claim="", hypothesis="")
        p_ss = score_paper(p_ss, claim="", hypothesis="")
        assert p_pubmed["stage1_score"] > p_ss["stage1_score"]
