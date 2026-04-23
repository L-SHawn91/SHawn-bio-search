"""Regression tests for shawn_bio_search.sources.accession_resolver.

Fixtures are known-good (accession, expected canonical type, expected first author, year, journal) tuples
derived from 2026-04-23 Paper2 audit. Each fixture exercises a different resolver source module.

These tests hit live NCBI / EBI / NGDC / CNGB endpoints and are therefore marked as network.
Run explicitly with:

    pytest tests/test_accession_resolver.py -m network

They should pass as long as the underlying APIs remain accessible and the study's GEO/BioStudies/IDF
records keep linking the expected PubMed ID.
"""

from __future__ import annotations

import pytest

from shawn_bio_search.sources.accession_resolver import (
    classify_tier,
    resolve_accession,
    format_citation,
    parse_accession_cell,
)


pytestmark = pytest.mark.network


# -------------------------------------------------------------------------
# classify_tier — offline, pure string
# -------------------------------------------------------------------------

CLASSIFY_CASES = [
    ("GSE108570",   "citation_unit", "GSE",          "ncbi_geo"),
    ("GSM769052",   "analysis_unit", "GSM",          "ncbi_geo"),
    ("SRP127622",   "citation_unit", "SRP",          "ncbi_sra"),
    ("SRX087151",   "analysis_unit", "SRX",          "ncbi_sra"),
    ("SRR1234567",  "analysis_unit", "SRR",          "ncbi_sra"),
    ("PRJNA144887", "citation_unit", "PRJNA",        "ncbi_bioproject"),
    ("PRJEB37831",  "citation_unit", "PRJEB",        "ebi_ena"),
    ("PRJDB5890",   "citation_unit", "PRJDB",        "ddbj"),
    ("PRJCA023129", "citation_unit", "PRJCA",        "ngdc_gsa"),
    ("E-MTAB-13085","citation_unit", "ArrayExpress", "ebi_arrayexpress"),
    ("CRA001234",   "citation_unit", "CRA",          "ngdc_gsa"),
    ("HRA001234",   "citation_unit", "HRA",          "ngdc_gsa"),
    ("OMIX006591",  "citation_unit", "OMIX",         "ngdc_omix"),
    ("CNP0001234",  "citation_unit", "CNP",          "cngb"),
    ("PMC6535221",  "pmcid",         "PMC",          "ncbi_pmc"),
    ("XYZ99999",    "unknown",       "unknown",      "unknown"),
]


@pytest.mark.parametrize("acc,tier,type_,source", CLASSIFY_CASES)
def test_classify_tier(acc: str, tier: str, type_: str, source: str) -> None:
    cls = classify_tier(acc)
    assert cls["tier"] == tier, f"{acc}: expected tier={tier}, got {cls}"
    assert cls["type"] == type_, f"{acc}: expected type={type_}, got {cls}"
    assert cls["source"] == source, f"{acc}: expected source={source}, got {cls}"


# -------------------------------------------------------------------------
# parse_accession_cell — multi-accession strings
# -------------------------------------------------------------------------

PARSE_CASES = [
    ("GSE180637 + GSE193007", ["GSE180637", "GSE193007"]),
    ("E-MTAB-10287 + E-MTAB-10283", ["E-MTAB-10287", "E-MTAB-10283"]),
    ("GSE1 ; GSE2 , SRP3", ["GSE1", "GSE2", "SRP3"]),
    ("PRJCA023129 (OMIX006591 subset)", ["PRJCA023129", "OMIX006591"]),
    ("", []),
    ("no accessions here", []),
]


@pytest.mark.parametrize("cell,expected", PARSE_CASES)
def test_parse_accession_cell(cell: str, expected: list[str]) -> None:
    assert parse_accession_cell(cell) == expected


# -------------------------------------------------------------------------
# resolve_accession — per-source fixtures
# -------------------------------------------------------------------------

# (accession, expected_canonical, expected_first_author, expected_year, expected_journal_substring, expected_pmid)
RESOLVE_FIXTURES = [
    # NCBI GEO → GSE canonical, PMID
    ("GSE108570",   "GSE108570",   "Kim",      "2018", "Sci Rep",     "29615657"),
    # NCBI SRP → GSE preferred citation unit
    ("SRP127622",   "GSE108570",   "Kim",      "2018", "Sci Rep",     "29615657"),
    # NCBI SRX → Analysis unit resolved to study
    ("SRX087151",   "PRJNA144887", "Liu",      "2012", "J Biol Chem", "22378788"),
    # NCBI PRJNA with PubMed link
    ("PRJNA144887", "PRJNA144887", "Liu",      "2012", "J Biol Chem", "22378788"),
    # NCBI PMC → PMID
    ("PMC6535221",  "PMC6535221",  "La",       "2019", "PeerJ",       "31198626"),
]


@pytest.mark.parametrize("acc,expect_canonical,expect_author,expect_year,expect_journal_sub,expect_pmid", RESOLVE_FIXTURES)
def test_resolve_ncbi(acc: str, expect_canonical: str, expect_author: str, expect_year: str, expect_journal_sub: str, expect_pmid: str) -> None:
    r = resolve_accession(acc)
    assert r["canonical"] == expect_canonical, f"{acc}: canonical mismatch — got {r['canonical']}"
    assert r["pmid"] == expect_pmid, f"{acc}: PMID mismatch — got {r['pmid']}"
    cite = r.get("citation") or {}
    assert cite.get("first_author") == expect_author, f"{acc}: author — got {cite}"
    assert cite.get("year") == expect_year, f"{acc}: year — got {cite}"
    assert expect_journal_sub.lower() in cite.get("journal", "").lower(), f"{acc}: journal — got {cite}"


# -------------------------------------------------------------------------
# resolve_accession — non-NCBI sources (may be flaky; assert PMID resolves or structured note present)
# -------------------------------------------------------------------------

NONNCBI_FIXTURES = [
    # NGDC OMIX: OMIX006591 -> PRJCA023129 -> Zhou 2024 Stem Cell Res Ther (verified 2026-04-23)
    ("OMIX006591", {"bioproject_prefix": "PRJCA", "pmid_present": True}),
    # CNGB: CNP0004966 -> Wu 2024 Cell Discov 10:110 via Europe PMC fulltext (verified 2026-04-23)
    ("CNP0004966", {"pmid_present": True}),
    # ArrayExpress: IDF or Europe PMC fallback. E-MTAB-13085 Europe PMC hit is first-result — may rotate.
    ("E-MTAB-13085", {"pmid_present": True}),
]


@pytest.mark.parametrize("acc,expects", NONNCBI_FIXTURES)
def test_resolve_nonncbi(acc: str, expects: dict) -> None:
    r = resolve_accession(acc)
    if "bioproject_prefix" in expects:
        bp = r.get("bioproject") or ""
        assert bp.startswith(expects["bioproject_prefix"]), f"{acc}: bioproject — got {r}"
    if "pmid_present" in expects:
        assert r.get("pmid") is not None or "Europe PMC" in (r.get("note") or ""), f"{acc}: expected PMID or note — got {r}"


# -------------------------------------------------------------------------
# format_citation
# -------------------------------------------------------------------------

def test_format_citation_none() -> None:
    assert format_citation(None) == "-- no PMID linked --"


def test_format_citation_full() -> None:
    s = format_citation({
        "first_author": "Kim",
        "year": "2018",
        "journal": "Sci Rep",
        "volume": "8",
        "pages": "5436",
        "pmid": "29615657",
    })
    assert s == "Kim et al. 2018 Sci Rep 8:5436 (PMID 29615657)"
