"""Offline unit tests for rank_gap-based confidence classification.

These tests cover _classify_with_gap() and _assign_confidence_with_gap() which
implement the relative-ranking HIGH gate introduced in P0-B of the 2026-04-17
evaluation. No network calls — safe to run in CI.
"""
from shawn_bio_search.sources.pubmed import (
    _assign_confidence_with_gap,
    _classify_with_gap,
    _score_to_confidence,
)


# ---------------------------------------------------------------------------
# _classify_with_gap — truth table
# ---------------------------------------------------------------------------

def test_high_requires_both_score_and_gap():
    # high score + big gap → HIGH
    assert _classify_with_gap(0.80, 0.30) == "HIGH"
    # high score but tiny gap → downgrade to MEDIUM
    assert _classify_with_gap(0.80, 0.10) == "MEDIUM"


def test_high_boundary_conditions():
    # exact boundary is HIGH
    assert _classify_with_gap(0.55, 0.15) == "HIGH"
    # just below score boundary
    assert _classify_with_gap(0.54, 0.50) == "MEDIUM"
    # just below gap boundary
    assert _classify_with_gap(0.55, 0.14) == "MEDIUM"


def test_medium_low_unlikely_thresholds():
    assert _classify_with_gap(0.45, 0.00) == "MEDIUM"
    assert _classify_with_gap(0.35, 0.00) == "LOW"
    assert _classify_with_gap(0.25, 0.00) == "LOW"
    assert _classify_with_gap(0.24, 0.99) == "UNLIKELY"


def test_score_only_confidence_still_available():
    # Back-compat for non-top candidates
    assert _score_to_confidence(0.80) == "HIGH"
    assert _score_to_confidence(0.50) == "MEDIUM"
    assert _score_to_confidence(0.30) == "LOW"
    assert _score_to_confidence(0.10) == "UNLIKELY"


# ---------------------------------------------------------------------------
# _assign_confidence_with_gap — integration over candidate lists
# ---------------------------------------------------------------------------

def test_assign_clear_winner():
    """Top candidate separates clearly from runner-ups → HIGH."""
    cands = [
        {"_context_score": 0.92},
        {"_context_score": 0.40},
        {"_context_score": 0.35},
    ]
    _assign_confidence_with_gap(cands)
    assert cands[0]["_rank_gap"] == 0.52
    assert cands[0]["_verification_confidence"] == "HIGH"
    # Non-top keeps score-only semantics (gap = 0 by design)
    assert cands[1]["_rank_gap"] == 0.0
    assert cands[1]["_verification_confidence"] == "MEDIUM"
    assert cands[2]["_verification_confidence"] == "LOW"


def test_assign_ambiguous_top_is_downgraded():
    """Top candidate has a near-tie runner-up — must NOT return HIGH."""
    cands = [
        {"_context_score": 0.70},
        {"_context_score": 0.65},
        {"_context_score": 0.35},
    ]
    _assign_confidence_with_gap(cands)
    # gap 0.05 < 0.15 threshold → MEDIUM even though score 0.70 > 0.55
    assert cands[0]["_rank_gap"] == 0.05
    assert cands[0]["_verification_confidence"] == "MEDIUM"


def test_assign_single_candidate_gets_full_gap():
    """A sole candidate is treated as fully separated (gap = 1.0)."""
    cands = [{"_context_score": 0.60}]
    _assign_confidence_with_gap(cands)
    assert cands[0]["_rank_gap"] == 1.0
    assert cands[0]["_verification_confidence"] == "HIGH"


def test_assign_all_tied_at_base_score():
    """5 candidates all at base 0.35 — nothing becomes HIGH."""
    cands = [{"_context_score": 0.35} for _ in range(5)]
    _assign_confidence_with_gap(cands)
    assert all(c["_verification_confidence"] == "LOW" for c in cands)
    assert all(c["_rank_gap"] == 0.0 or c["_rank_gap"] == 0.0 for c in cands)


def test_assign_empty_list_is_noop():
    cands = []
    _assign_confidence_with_gap(cands)  # must not raise
    assert cands == []
