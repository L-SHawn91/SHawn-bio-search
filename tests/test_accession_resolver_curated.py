"""Offline regression tests for accession resolver curated safeguards."""

from __future__ import annotations

from shawn_bio_search.sources import accession_resolver as ar


def test_curated_arrayexpress_endometrium_producer_mappings() -> None:
    for acc in ("E-MTAB-10287", "E-MTAB-10283", "E-MTAB-9260"):
        resolved = ar.resolve_accession(acc)

        assert resolved["pmid"] == "34857954"
        assert resolved["resolver_source"] == "curated_accession_override"
        assert resolved["citation"]["first_author"] == "Garcia-Alonso"
        assert resolved["citation"]["journal"] == "Nat Genet"


def test_curated_heca_mapping() -> None:
    resolved = ar.resolve_accession("E-MTAB-14039")

    assert resolved["pmid"] == "39198675"
    assert resolved["resolver_source"] == "curated_accession_override"
    assert resolved["citation"]["first_author"] == "Mareckova"
    assert resolved["citation"]["journal"] == "Nat Genet"


def test_curated_gse_without_geo_pubmed_id_mapping() -> None:
    resolved = ar.resolve_accession("GSE222544")

    assert resolved["bioproject"] == "PRJNA922493"
    assert resolved["pmid"] == "38748354"
    assert resolved["resolver_source"] == "curated_accession_override"
    assert resolved["citation"]["first_author"] == "Zang"
    assert resolved["citation"]["journal"] == "Sci China Life Sci"


def test_curated_manuscript_geo_metadata_gap_mappings() -> None:
    expected = {
        "GSE180637": ("37054708", "Jiang", "Dev Cell"),
        "GSE193007": ("36517595", "Zhai", "Nature"),
        "GSE289073": ("41574608", "Burns", "JCI Insight"),
        "GSE310372": ("41236135", "Edge", "Biol Reprod"),
        "GSE31041": ("22378788", "Liu", "J Biol Chem"),
    }

    for acc, (pmid, first_author, journal) in expected.items():
        resolved = ar.resolve_accession(acc)

        assert resolved["pmid"] == pmid
        assert resolved["resolver_source"] == "curated_accession_override"
        assert resolved["citation"]["first_author"] == first_author
        assert resolved["citation"]["journal"] == journal


def test_arrayexpress_europepmc_candidates_are_not_promoted(monkeypatch) -> None:
    monkeypatch.setattr(ar, "_ebi_biostudies_json_pmids", lambda acc: {"pmids": []})
    monkeypatch.setattr(ar, "_ebi_arrayexpress_idf", lambda acc: {"pmids": []})
    monkeypatch.setattr(ar, "_ebi_europepmc_search_accession", lambda acc: ["12345", "67890"])

    resolved = ar.resolve_accession("E-MTAB-999999")

    assert resolved["pmid"] is None
    assert resolved["citation"] is None
    assert "Europe PMC first-hit candidates not promoted" in resolved["note"]
    assert "12345, 67890" in resolved["resolution_path"][0]
