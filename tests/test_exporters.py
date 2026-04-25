"""Offline tests for citation exporters (BibTeX, RIS, CSL-JSON)."""

from __future__ import annotations

import json

from shawn_bio_search import exporters


SAMPLE = [
    {
        "title": "Long-term hormone-responsive organoid cultures of human endometrium",
        "authors": ["Turco MY", "Gardner L", "Hughes J"],
        "year": 2017,
        "journal": "Nature Cell Biology",
        "doi": "10.1038/ncb3516",
        "pmid": "28394884",
        "url": "https://www.nature.com/articles/ncb3516",
        "abstract": "Endometrial organoids were established...",
    },
    {
        "title": "Designer matrices for intestinal stem cell and organoid culture",
        "authors": [{"name": "Gjorevski N"}, {"name": "Sachs N"}],
        "year": 2016,
        "journal": "Nature",
        "doi": "10.1038/nature20168",
    },
]


def test_citation_key_uses_explicit_when_present():
    paper = {"citation_key": "smith2020", "year": 2020}
    assert exporters.citation_key(paper) == "smith2020"


def test_citation_key_builds_surname_year_word():
    paper = {
        "title": "An organoid model of disease",
        "authors": ["Turco MY", "Gardner L"],
        "year": 2017,
    }
    key = exporters.citation_key(paper)
    assert key.startswith("turco") and "2017" in key and "organoid" in key


def test_citation_key_falls_back_when_minimal():
    assert exporters.citation_key({}) == "untitled"


def test_to_bibtex_emits_one_entry_per_paper():
    out = exporters.to_bibtex(SAMPLE)
    assert out.count("@article{") == 2
    assert "doi = {10.1038/ncb3516}" in out
    assert "title = {Long-term hormone-responsive organoid cultures" in out


def test_to_bibtex_escapes_braces():
    paper = {"title": "Curly {brace} title", "authors": ["Doe J"], "year": 2020}
    out = exporters.to_bibtex([paper])
    assert "Curly \\{brace\\} title" in out


def test_to_bibtex_skips_empty_fields():
    paper = {"title": "X", "authors": ["Doe J"], "year": 2020}
    out = exporters.to_bibtex([paper])
    assert "doi" not in out
    assert "abstract" not in out


def test_to_ris_round_trips_required_tags():
    out = exporters.to_ris(SAMPLE)
    records = out.strip().split("\n\n")
    assert len(records) == 2
    first = records[0]
    assert first.startswith("TY  - JOUR")
    assert "AU  - Turco MY" in first
    assert "TI  - Long-term hormone-responsive" in first
    assert "DO  - 10.1038/ncb3516" in first
    assert first.rstrip().endswith("ER  -")


def test_to_csl_json_is_valid_json_array():
    out = exporters.to_csl_json(SAMPLE)
    items = json.loads(out)
    assert isinstance(items, list) and len(items) == 2
    first = items[0]
    assert first["type"] == "article-journal"
    assert first["DOI"] == "10.1038/ncb3516"
    assert first["issued"] == {"date-parts": [[2017]]}
    assert first["author"][0] == {"family": "Turco", "given": "MY"}


def test_to_csl_json_handles_dict_authors():
    out = exporters.to_csl_json([SAMPLE[1]])
    item = json.loads(out)[0]
    assert item["author"][0]["family"] == "Gjorevski N"


def test_empty_input_produces_empty_or_array():
    assert exporters.to_bibtex([]) == ""
    assert exporters.to_ris([]) == ""
    assert exporters.to_csl_json([]) == "[]"
