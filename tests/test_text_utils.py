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
