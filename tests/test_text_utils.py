from shawn_bio_search.text_utils import (
    dedupe_key,
    merge_unique_list,
    overlap_ratio,
    tokenize,
)


def test_tokenize_normal():
    toks = tokenize("Endometrial Organoids model UTERINE biology.")
    assert toks == {"endometrial", "organoids", "model", "uterine", "biology"}


def test_tokenize_drops_short_and_handles_empty():
    assert tokenize("a is in") == set()
    assert tokenize("") == set()
    assert tokenize(None) == set()  # type: ignore[arg-type]


def test_overlap_ratio_normal():
    base = "endometrial organoid culture"
    target = "long-term endometrial organoid hormone-responsive culture"
    ratio = overlap_ratio(base, target)
    # all 3 base tokens (endometrial, organoid, culture) appear in target
    assert ratio == 1.0


def test_overlap_ratio_empty_sides_are_zero():
    assert overlap_ratio("", "anything") == 0.0
    assert overlap_ratio("anything", "") == 0.0
    assert overlap_ratio("a is in", "anything") == 0.0  # no >=3-letter tokens


def test_dedupe_key_prefers_doi_then_title_then_id():
    assert dedupe_key({"doi": "10.1/A", "title": "x", "id": "y"}) == ("doi", "10.1/a")
    assert dedupe_key({"doi": "", "title": "Some Title", "id": "y"}) == ("title", "some title")
    assert dedupe_key({"doi": None, "title": None, "id": " ABC "}) == ("id", "abc")


def test_dedupe_key_blank_record_returns_id_empty():
    assert dedupe_key({}) == ("id", "")


def test_merge_unique_list_preserves_order_and_dedups_case_insensitively():
    out = merge_unique_list(["pubmed", "OpenAlex"], ["openalex", "crossref"])
    assert out == ["pubmed", "OpenAlex", "crossref"]


def test_merge_unique_list_handles_none_and_blanks():
    assert merge_unique_list(None, None) == []
    assert merge_unique_list(["", "  "], ["x"]) == ["x"]


# ── Synonym-aware overlap tests ────────────────────────────────────────────

def test_overlap_ratio_synonym_cancer_carcinoma():
    """'cancer' and 'carcinoma' should match via synonym group."""
    base = "endometrial cancer POLE mutation"
    target = "uterine carcinoma genomic instability variant"
    ratio = overlap_ratio(base, target)
    # 'endometrial'/'uterine' match, 'cancer'/'carcinoma' match, 'mutation'/'variant' match → ≥3/4
    assert ratio >= 0.60, f"Expected ≥0.60, got {ratio:.3f}"


def test_overlap_ratio_mutation_variant():
    """'mutation' and 'variant' are synonyms."""
    assert overlap_ratio("POLE mutation", "POLE variant") > overlap_ratio("POLE mutation", "POLE xyz_zzz")


def test_overlap_ratio_endometrial_uterine():
    """'endometrial' and 'uterine' are synonyms."""
    ratio = overlap_ratio("endometrial cancer", "uterine carcinoma")
    assert ratio >= 0.80, f"Expected ≥0.80, got {ratio:.3f}"


def test_overlap_ratio_no_false_synonyms():
    """Unrelated terms must not get spurious synonym credit."""
    # 'liver' is not in any synonym group for endometrial terms
    ratio = overlap_ratio("endometrial cancer receptivity", "liver cirrhosis fibrosis")
    assert ratio < 0.20, f"Expected <0.20, got {ratio:.3f}"


def test_overlap_ratio_hormone_synonyms():
    """'progesterone' and 'progestin' are synonyms."""
    ratio = overlap_ratio("progesterone signaling", "progestin pathway")
    assert ratio >= 0.80, f"Expected ≥0.80, got {ratio:.3f}"


def test_synonym_improves_scoring_vs_old():
    """Synonym overlap must be strictly higher than pure lexical for known mismatch."""
    from shawn_bio_search.text_utils import _syn_ids, tokenize as _tok
    base_raw = _tok("endometrial cancer mutation")
    target_raw = _tok("uterine carcinoma variant")
    raw_overlap = len(base_raw & target_raw) / len(base_raw)

    syn_overlap = overlap_ratio("endometrial cancer mutation", "uterine carcinoma variant")
    assert syn_overlap > raw_overlap, f"Synonym overlap {syn_overlap:.3f} not > raw {raw_overlap:.3f}"
