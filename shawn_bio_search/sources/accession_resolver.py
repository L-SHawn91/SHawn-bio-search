"""Accession resolver — dataset accession → canonical citation unit + PMID + formal citation.

Single public entry point for resolving NCBI / EBI / DDBJ / NGDC / CNGB identifiers across
the federated bioinformatics ecosystem. Enforces the SHawn house rule that every dataset has
two accession tiers:

  (A) Citation Unit — used when citing the study in a paper / table.
      Precedence: GSE > PRJNA > SRP > E-MTAB > PRJEB > PRJDB > CRA > HRA > PRJCA > CNP > OMIX
  (B) Analysis Unit — sample / library / run level, used when downloading FASTQ.
      GSM, SRX, SRR, ERR, DRR, CRR, CNR. Never cited as a study.

Supported sources (prefix → dispatcher → per-source module):

    NCBI GEO        GSE*, GSM*                  (eutils + geo acc.cgi)
    NCBI SRA        SRP*, SRX*, SRR*             (eutils gds + elink)
    NCBI BioProject PRJNA*                       (eutils bioproject + elink)
    NCBI PMC        PMC*                         (idconv.v1.0)
    EBI ArrayExpress E-MTAB-*, E-GEOD-*, E-PROT-*, E-ENAD-*
                                                 (BioStudies JSON + IDF text fallback + Europe PMC)
    EBI BioStudies  S-BSST*, S-EPMC*             (BioStudies JSON)
    EBI ENA         PRJEB*, ERP*, ERX*, ERR*     (ENA browser XML API)
    DDBJ            PRJDB*, DRP*, DRX*, DRR*     (INSDC cross-link via NCBI eutils bioproject)
    NGDC GSA        CRA*, HRA*, PRJCA*           (HTML scrape — no public REST)
    NGDC OMIX       OMIX*                        (HTML scrape — no public REST)
    CNGB            CNP*, CNX*, CNR*             (HTML scrape — no public REST)
    CNGB CDCP       SCDS*                        (HTML scrape → forwards to linked GSE/CNP/PRJCA)

All HTTP calls route through `_http.http_json` / `http_text` which share rate-limit +
retry state. Direct `urllib.request` is avoided so bio-search is the only API chokepoint
(CLAUDE.md "no manual API calls" rule).

Root cause record: 2026-04-23 Paper2 S1b audit — SRP127622 used in place of canonical
GSE108570 (Kim 2018 Sci Rep 8:5436); SRX087151 listed as a separate study when it was a
D15 sample of GSE31041 (Liu 2012 JBC); 3 rows referenced wrong first authors; 18 rows
used "YEAR" placeholders. Root cause = no canonical/analysis tier separation and no
BioProject dedup key. This module enforces both.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from ._http import http_json, http_text


def _eutils_url(path: str) -> str:
    """Build an NCBI eutils URL, appending api_key + polite email when available."""
    url = f"{NCBI_EUTILS}/{path}"
    extras: list[str] = []
    key = os.environ.get("NCBI_API_KEY")
    if key:
        extras.append(f"api_key={key}")
    email = os.environ.get("CROSSREF_EMAIL") or os.environ.get("UNPAYWALL_EMAIL")
    if email:
        extras.append(f"email={email}")
    if extras:
        sep = "&" if "?" in url else "?"
        url += sep + "&".join(extras)
    return url


# =====================================================================
# Endpoints
# =====================================================================

NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GEO_ACC_BASE = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
PMC_IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
BIOSTUDIES_API = "https://www.ebi.ac.uk/biostudies/api/v1/studies"
BIOSTUDIES_FILES = "https://www.ebi.ac.uk/biostudies/files"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ENA_BROWSER = "https://www.ebi.ac.uk/ena/browser/api/xml"
NGDC_OMIX_RELEASE = "https://ngdc.cncb.ac.cn/omix/release"
NGDC_GSA_BROWSE = "https://ngdc.cncb.ac.cn/gsa/browse"
CNGB_PROJECT = "https://db.cngb.org/search/project"
CNGB_CDCP_DATASET = "https://db.cngb.org/cdcp/dataset"

_USER_AGENT = "SHawn-bio-search/0.1 (accession-resolver)"


# =====================================================================
# Accession classification
# =====================================================================

CITATION_UNIT_PREFIXES = (
    "GSE", "PRJNA", "PRJEB", "PRJDB", "PRJCA", "SRP", "DRP", "ERP",
    "E-MTAB", "E-GEOD", "E-PROT", "E-ENAD", "S-BSST", "S-EPMC",
    "CRA", "HRA", "OMIX", "CNP", "SCDS",
)
ANALYSIS_UNIT_PREFIXES = ("GSM", "SRX", "SRR", "DRX", "DRR", "ERX", "ERR", "CNX", "CNR", "CRX", "CRR")
CITATION_PRIORITY = (
    "GSE", "PRJNA", "PRJEB", "PRJDB", "PRJCA",
    "SRP", "DRP", "ERP",
    "ArrayExpress", "BioStudies",
    "CRA", "HRA", "OMIX", "CNP",
)


def classify_tier(accession: str) -> Dict[str, str]:
    """Return {tier, type, source} for an accession. Covers every known prefix."""
    acc = accession.strip().upper()
    # Citation units
    if acc.startswith("GSE"):
        return {"tier": "citation_unit", "type": "GSE", "source": "ncbi_geo"}
    if acc.startswith("PRJNA"):
        return {"tier": "citation_unit", "type": "PRJNA", "source": "ncbi_bioproject"}
    if acc.startswith("PRJEB"):
        return {"tier": "citation_unit", "type": "PRJEB", "source": "ebi_ena"}
    if acc.startswith("PRJDB"):
        return {"tier": "citation_unit", "type": "PRJDB", "source": "ddbj"}
    if acc.startswith("PRJCA"):
        return {"tier": "citation_unit", "type": "PRJCA", "source": "ngdc_gsa"}
    if acc.startswith("SRP"):
        return {"tier": "citation_unit", "type": "SRP", "source": "ncbi_sra"}
    if acc.startswith("ERP"):
        return {"tier": "citation_unit", "type": "ERP", "source": "ebi_ena"}
    if acc.startswith("DRP"):
        return {"tier": "citation_unit", "type": "DRP", "source": "ddbj"}
    if acc.startswith(("E-MTAB", "E-GEOD", "E-PROT", "E-ENAD")):
        return {"tier": "citation_unit", "type": "ArrayExpress", "source": "ebi_arrayexpress"}
    if acc.startswith(("S-BSST", "S-EPMC")):
        return {"tier": "citation_unit", "type": "BioStudies", "source": "ebi_biostudies"}
    if acc.startswith("CRA"):
        return {"tier": "citation_unit", "type": "CRA", "source": "ngdc_gsa"}
    if acc.startswith("HRA"):
        return {"tier": "citation_unit", "type": "HRA", "source": "ngdc_gsa"}
    if acc.startswith("OMIX"):
        return {"tier": "citation_unit", "type": "OMIX", "source": "ngdc_omix"}
    if acc.startswith("CNP"):
        return {"tier": "citation_unit", "type": "CNP", "source": "cngb"}
    if acc.startswith("SCDS"):
        return {"tier": "citation_unit", "type": "SCDS", "source": "cngb_cdcp"}

    # Analysis units
    if acc.startswith("GSM"):
        return {"tier": "analysis_unit", "type": "GSM", "source": "ncbi_geo"}
    if acc.startswith("SRX"):
        return {"tier": "analysis_unit", "type": "SRX", "source": "ncbi_sra"}
    if acc.startswith("SRR"):
        return {"tier": "analysis_unit", "type": "SRR", "source": "ncbi_sra"}
    if acc.startswith("ERX"):
        return {"tier": "analysis_unit", "type": "ERX", "source": "ebi_ena"}
    if acc.startswith("ERR"):
        return {"tier": "analysis_unit", "type": "ERR", "source": "ebi_ena"}
    if acc.startswith("DRX"):
        return {"tier": "analysis_unit", "type": "DRX", "source": "ddbj"}
    if acc.startswith("DRR"):
        return {"tier": "analysis_unit", "type": "DRR", "source": "ddbj"}
    if acc.startswith("CRX"):
        return {"tier": "analysis_unit", "type": "CRX", "source": "ngdc_gsa"}
    if acc.startswith("CRR"):
        return {"tier": "analysis_unit", "type": "CRR", "source": "ngdc_gsa"}
    if acc.startswith("CNX"):
        return {"tier": "analysis_unit", "type": "CNX", "source": "cngb"}
    if acc.startswith("CNR"):
        return {"tier": "analysis_unit", "type": "CNR", "source": "cngb"}

    # PMCID
    if acc.startswith("PMC"):
        return {"tier": "pmcid", "type": "PMC", "source": "ncbi_pmc"}

    return {"tier": "unknown", "type": "unknown", "source": "unknown"}


# =====================================================================
# Citation formatting
# =====================================================================

def format_citation(cite: Optional[Dict[str, str]]) -> str:
    if not cite:
        return "-- no PMID linked --"
    j = cite.get("journal", "")
    v = cite.get("volume", "")
    p = cite.get("pages", "")
    tail = f"{v}:{p}" if v and p else v or p
    pmid = cite.get("pmid", "")
    pmid_s = f" (PMID {pmid})" if pmid else ""
    return f"{cite.get('first_author','?')} et al. {cite.get('year','?')} {j} {tail}{pmid_s}".strip()


def pmid_to_citation(pmid: str) -> Optional[Dict[str, str]]:
    """PMID → structured citation dict via NCBI esummary."""
    try:
        d = http_json(_eutils_url(f"esummary.fcgi?db=pubmed&id={pmid}&retmode=json"),
                      headers={"User-Agent": _USER_AGENT})
    except Exception:
        return None
    rec = d.get("result", {}).get(str(pmid), {})
    if not rec:
        return None
    authors = rec.get("authors", [])
    first = authors[0].get("name", "").split()[0] if authors else ""
    year = (rec.get("pubdate", "") + " ").split()[0]
    return {
        "first_author": first,
        "year": year,
        "journal": rec.get("source", ""),
        "volume": rec.get("volume", ""),
        "pages": rec.get("pages", ""),
        "title": rec.get("title", ""),
        "pmid": str(pmid),
    }


# =====================================================================
# NCBI source functions
# =====================================================================

def _ncbi_pmcid_to_pmid(pmcid: str) -> Optional[str]:
    """PMC* -> PMID via NCBI ID Converter."""
    clean = pmcid.strip().upper()
    if not clean.startswith("PMC"):
        clean = "PMC" + clean
    try:
        d = http_json(f"{PMC_IDCONV}?ids={clean}&format=json",
                      headers={"User-Agent": _USER_AGENT})
    except Exception:
        return None
    recs = d.get("records", [])
    if not recs:
        return None
    pmid = recs[0].get("pmid")
    return str(pmid) if pmid else None


def _ncbi_geo_series_record(gse: str) -> Dict[str, Any]:
    """GEO Series brief text record → PMIDs + title + BioProject."""
    try:
        raw = http_text(f"{GEO_ACC_BASE}?acc={gse}&targ=self&view=brief&form=text",
                        headers={"User-Agent": _USER_AGENT})
    except Exception as e:
        return {"pmids": [], "title": None, "bioproject": None, "error": str(e)}
    pmids = re.findall(r"!Series_pubmed_id\s*=\s*(\d+)", raw)
    title_m = re.search(r"!Series_title\s*=\s*(.+)", raw)
    bp_m = re.search(r"BioProject:\s*https?://\S*/bioproject/(PRJ\w+)", raw)
    return {
        "pmids": pmids,
        "title": title_m.group(1).strip() if title_m else None,
        "bioproject": bp_m.group(1) if bp_m else None,
    }


def _ncbi_sra_to_gse(srp_or_srx: str) -> List[str]:
    """SRP*/SRX* → GEO Series via gds esearch."""
    try:
        d = http_json(_eutils_url(f"esearch.fcgi?db=gds&term={srp_or_srx}+AND+gse%5BEntry+Type%5D&retmode=json"),
                      headers={"User-Agent": _USER_AGENT})
    except Exception:
        return []
    ids = [x for x in d.get("esearchresult", {}).get("idlist", []) if x.startswith("200")]
    accs: List[str] = []
    for gid in ids[:3]:
        try:
            s = http_json(_eutils_url(f"esummary.fcgi?db=gds&id={gid}&retmode=json"),
                          headers={"User-Agent": _USER_AGENT})
            acc = s.get("result", {}).get(gid, {}).get("accession")
            if acc:
                accs.append(acc)
        except Exception:
            continue
    return accs


def _ncbi_sra_to_bioproject(srp_or_srx: str) -> List[str]:
    """SRP*/SRX*/SRR* → PRJNA* via elink dbfrom=sra db=bioproject."""
    try:
        d = http_json(_eutils_url(f"esearch.fcgi?db=sra&term={srp_or_srx}&retmode=json"),
                      headers={"User-Agent": _USER_AGENT})
    except Exception:
        return []
    sra_ids = d.get("esearchresult", {}).get("idlist", [])
    if not sra_ids:
        return []
    try:
        link = http_json(_eutils_url(f"elink.fcgi?dbfrom=sra&db=bioproject&id={sra_ids[0]}&retmode=json"),
                         headers={"User-Agent": _USER_AGENT})
    except Exception:
        return []
    linksets = link.get("linksets", [])
    if not linksets or not linksets[0].get("linksetdbs"):
        return []
    bp_uids = [str(x) for x in linksets[0]["linksetdbs"][0].get("links", [])]
    accs: List[str] = []
    for uid in bp_uids[:2]:
        try:
            s = http_json(_eutils_url(f"esummary.fcgi?db=bioproject&id={uid}&retmode=json"),
                          headers={"User-Agent": _USER_AGENT})
            acc = s.get("result", {}).get(uid, {}).get("project_acc")
            if acc:
                accs.append(acc)
        except Exception:
            continue
    return accs


def _ncbi_bioproject_to_pmids(prj: str) -> List[str]:
    """PRJNA* / PRJEB* / PRJDB* → PubMed IDs via elink.

    PRJEB / PRJDB work because INSDC cross-mirrors BioProject entries; NCBI bioproject
    db contains ENA and DDBJ registrations too.
    """
    try:
        d = http_json(_eutils_url(f"esearch.fcgi?db=bioproject&term={prj}&retmode=json"),
                      headers={"User-Agent": _USER_AGENT})
    except Exception:
        return []
    ids = d.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    try:
        link = http_json(_eutils_url(f"elink.fcgi?dbfrom=bioproject&db=pubmed&id={ids[0]}&retmode=json"),
                         headers={"User-Agent": _USER_AGENT})
    except Exception:
        return []
    linksets = link.get("linksets", [])
    if not linksets or not linksets[0].get("linksetdbs"):
        return []
    return [str(p) for p in linksets[0]["linksetdbs"][0].get("links", [])]


# =====================================================================
# EBI ArrayExpress / BioStudies source functions
# =====================================================================

def _ebi_biostudies_json_pmids(acc: str) -> Dict[str, Any]:
    """Parse BioStudies JSON attrs for PubMed ID + title. Often misses PMID though."""
    try:
        d = http_json(f"{BIOSTUDIES_API}/{acc}", headers={"User-Agent": _USER_AGENT})
    except Exception as e:
        return {"pmids": [], "title": None, "error": str(e)}
    pmids: List[str] = []
    title: Optional[str] = None

    def walk(obj: Any) -> None:
        nonlocal title
        if isinstance(obj, dict):
            attrs = obj.get("attributes", [])
            for a in attrs:
                name = (a.get("name") or "").lower()
                val = a.get("value")
                if name == "title" and title is None:
                    title = val
                if name in ("pubmed id", "pmid") and val:
                    s = str(val).strip()
                    if s.isdigit() and len(s) >= 5:
                        pmids.append(s)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)
    walk(d)
    return {"pmids": list(dict.fromkeys(pmids)), "title": title}


def _ebi_arrayexpress_idf(acc: str) -> Dict[str, Any]:
    """Parse ArrayExpress IDF (MAGE-TAB) text file — the canonical place for PubMed ID."""
    try:
        raw = http_text(f"{BIOSTUDIES_FILES}/{acc}/{acc}.idf.txt",
                        headers={"User-Agent": _USER_AGENT})
    except Exception as e:
        return {"pmids": [], "title": None, "error": str(e)}
    pmids: List[str] = []
    title: Optional[str] = None
    for line in raw.splitlines():
        if "\t" not in line:
            continue
        fields = line.split("\t")
        tag = fields[0].strip().lower()
        values = [f.strip() for f in fields[1:] if f.strip()]
        if tag == "pubmed id":
            for v in values:
                if v.isdigit():
                    pmids.append(v)
        elif tag == "investigation title" and not title:
            title = values[0] if values else None
    return {"pmids": list(dict.fromkeys(pmids)), "title": title}


def _ebi_europepmc_search_accession(acc: str) -> List[str]:
    """Fallback: Europe PMC fulltext search for the accession string → PMIDs (first few)."""
    try:
        d = http_json(f"{EUROPEPMC_SEARCH}?query={acc}&format=json&pageSize=5&resultType=lite",
                      headers={"User-Agent": _USER_AGENT})
    except Exception:
        return []
    rows = d.get("resultList", {}).get("result", [])
    pmids: List[str] = []
    for r in rows:
        pmid = r.get("pmid")
        if pmid:
            pmids.append(str(pmid))
    return pmids


# =====================================================================
# EBI ENA source functions
# =====================================================================

def _ebi_ena_metadata(acc: str) -> Dict[str, Any]:
    """ENA browser XML API for PRJEB / ERP / ERX / ERR. Yields BioProject + linked PubMed if any."""
    try:
        raw = http_text(f"{ENA_BROWSER}/{acc}", headers={"User-Agent": _USER_AGENT})
    except Exception as e:
        return {"pmids": [], "bioproject": None, "error": str(e)}
    # ENA XML has <XREF_LINK><DB>PUBMED</DB><ID>xxxx</ID>...
    pmid_m = re.findall(r"<DB>PUBMED</DB>\s*<ID>(\d+)</ID>", raw)
    prj_m = re.findall(r"<PRIMARY_ID>(PRJEB\d+)</PRIMARY_ID>", raw) or re.findall(r"(PRJEB\d+)", raw)
    bp = prj_m[0] if prj_m else None
    return {"pmids": list(dict.fromkeys(pmid_m)), "bioproject": bp}


# =====================================================================
# NGDC (China National Center for Bioinformation) source functions
# =====================================================================

def _ngdc_omix_html(acc: str) -> Dict[str, Any]:
    """NGDC OMIX release page scrape. Returns linked PRJCA / PubMed / title."""
    try:
        raw = http_text(f"{NGDC_OMIX_RELEASE}/{acc}",
                        headers={"User-Agent": _USER_AGENT,
                                 "Accept": "text/html"})
    except Exception as e:
        return {"pmids": [], "bioproject": None, "title": None, "error": str(e)}
    prjca = re.findall(r"(PRJCA\d+)", raw)
    pmids = re.findall(r"PubMed(?:\s*ID)?[^0-9]{0,30}(\d{5,9})", raw, re.IGNORECASE)
    # Title: look for <title>...</title> or h1
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = title_m.group(1).strip() if title_m else None
    return {
        "pmids": list(dict.fromkeys(pmids)),
        "bioproject": prjca[0] if prjca else None,
        "title": title,
    }


def _ngdc_gsa_html(acc: str) -> Dict[str, Any]:
    """NGDC GSA browse scrape. For CRA / HRA / PRJCA accessions.

    The browse UI sometimes closes connections without response; include a single retry.
    """
    last_err: Optional[Exception] = None
    for _ in range(2):
        try:
            raw = http_text(f"{NGDC_GSA_BROWSE}/{acc}",
                            headers={"User-Agent": _USER_AGENT,
                                     "Accept": "text/html"})
            prjca = re.findall(r"(PRJCA\d+)", raw)
            pmids = re.findall(r"PubMed(?:\s*ID)?[^0-9]{0,30}(\d{5,9})", raw, re.IGNORECASE)
            title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
            return {
                "pmids": list(dict.fromkeys(pmids)),
                "bioproject": prjca[0] if prjca else (acc if acc.startswith("PRJCA") else None),
                "title": title_m.group(1).strip() if title_m else None,
            }
        except Exception as e:
            last_err = e
    return {"pmids": [], "bioproject": None, "title": None, "error": str(last_err)}


# =====================================================================
# CNGB source functions
# =====================================================================

def _cngb_cdcp_html(acc: str) -> Dict[str, Any]:
    """CDCP (Cell-omics Data Coordinate Platform) dataset page scrape.

    CDCP is a visualization/aggregator layer over multiple upstream archives. Its HTML
    shell contains navigation/footer links that happen to include sample GSE/CNP accessions
    — extracting those as "linked" cross-references produces false positives (a page for
    a non-existent SCDS still shows the same boilerplate GSE list). We therefore extract
    *only* what is genuinely page-specific:

      - `<title>` tag (dataset name)
      - `<meta name="description">` (study abstract)
      - Any PubMed/DOI references that appear inside the description itself

    Cross-archive accession forwarding (SCDS → GSE/CNP) is intentionally NOT done here;
    downstream resolver prefers Europe PMC fulltext for SCDS* because that path requires
    the accession to actually be cited in a paper, which is the stronger signal.
    """
    try:
        raw = http_text(f"{CNGB_CDCP_DATASET}/{acc}/",
                        headers={"User-Agent": _USER_AGENT, "Accept": "text/html"})
    except Exception as e:
        return {"error": str(e)}

    title_m = re.search(r"<title[^>]*>([^<]+?)\s*-\s*Single-cell Datasets", raw, re.IGNORECASE)
    if not title_m:
        title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = title_m.group(1).strip() if title_m else None

    desc_m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', raw, re.IGNORECASE)
    description = desc_m.group(1).strip() if desc_m else ""

    # If the page has no description and the title is the generic site title, treat as
    # "not found" (CDCP serves a shell for any /dataset/* URL).
    generic_title = (not title) or title.lower().startswith("cdcp") or "not found" in (title or "").lower()
    if generic_title and not description:
        return {"not_found": True, "title": title}

    # Extract only from description (never from shell)
    pmids_in_desc = list(dict.fromkeys(
        re.findall(r"PubMed(?:\s*ID)?[^0-9]{0,30}(\d{5,9})", description, re.IGNORECASE)))
    dois_in_desc = list(dict.fromkeys(re.findall(r"(10\.\d+/[^\"'\s<>,]+)", description)))[:3]

    return {
        "title": title,
        "description": description,
        "pmids": pmids_in_desc,
        "dois": dois_in_desc,
    }


def _cngb_html(acc: str) -> Dict[str, Any]:
    """CNGB project page scrape. For CNP* (study), CNX* / CNR* are analysis units."""
    try:
        raw = http_text(f"{CNGB_PROJECT}/{acc}/",
                        headers={"User-Agent": _USER_AGENT,
                                 "Accept": "text/html"})
    except Exception as e:
        return {"pmids": [], "title": None, "error": str(e)}
    pmids = re.findall(r"PubMed(?:\s*ID)?[^0-9]{0,30}(\d{5,9})", raw, re.IGNORECASE)
    dois = re.findall(r"(10\.\d+/[^\"'\s<>]+)", raw)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    return {
        "pmids": list(dict.fromkeys(pmids)),
        "dois": list(dict.fromkeys(dois))[:3],
        "title": title_m.group(1).strip() if title_m else None,
    }


# =====================================================================
# Public API — resolve_accession
# =====================================================================

def resolve_accession(accession: str) -> Dict[str, Any]:
    """Resolve a single accession to its study-level citation unit + PMID + formal citation.

    Returns:
        {
          "original":        str,   # input
          "canonical":       str,   # recommended citation-unit form
          "tier":            "citation_unit" | "analysis_unit" | "pmcid" | "unknown",
          "type":            "GSE" | "PRJNA" | "SRP" | "ArrayExpress" | "CRA" | ...,
          "source":          "ncbi_geo" | "ebi_ena" | "ngdc_gsa" | "cngb" | ...,
          "bioproject":      str | None,
          "pmid":            str | None,
          "citation":        dict | None,
          "note":            str | None,
          "resolution_path": list[str],  # audit trail
          "resolver_source": str,        # which module path was used
        }
    """
    acc = accession.strip()
    cls = classify_tier(acc)
    out: Dict[str, Any] = {
        "original": acc,
        "canonical": acc,
        "tier": cls["tier"],
        "type": cls["type"],
        "source": cls["source"],
        "bioproject": None,
        "pmid": None,
        "citation": None,
        "note": None,
        "resolution_path": [],
        "resolver_source": cls["source"],
    }

    if cls["tier"] == "unknown":
        out["note"] = "Accession prefix not recognised"
        return out

    # -----------------------------------------------------------------
    # PMCID
    # -----------------------------------------------------------------
    if cls["tier"] == "pmcid":
        pmid = _ncbi_pmcid_to_pmid(acc)
        if pmid:
            out["pmid"] = pmid
            out["citation"] = pmid_to_citation(pmid)
            out["resolution_path"].append(f"PMCID {acc} -> idconv -> PMID {pmid}")
        else:
            out["note"] = "PMCID resolved no PMID via idconv"
        return out

    # -----------------------------------------------------------------
    # Analysis units (GSM / SRX / SRR / ERX / ERR / DRX / DRR / CRX / CRR / CNX / CNR)
    # -----------------------------------------------------------------
    if cls["tier"] == "analysis_unit":
        out["note"] = f"Analysis Unit ({cls['type']}) — not a citation unit. Resolved via parent study."

        if cls["type"] in ("SRX", "SRR"):
            gses = _ncbi_sra_to_gse(acc)
            if gses:
                out["canonical"] = gses[0]
                out["type"] = "GSE"
                out["tier"] = "citation_unit"
                out["resolver_source"] = "ncbi_geo"
                rec = _ncbi_geo_series_record(gses[0])
                out["bioproject"] = rec.get("bioproject")
                pmids = rec.get("pmids", [])
                if pmids:
                    out["pmid"] = pmids[0]
                    out["citation"] = pmid_to_citation(pmids[0])
                out["resolution_path"].append(f"{acc} -> SRA -> GSE {gses[0]}")
                return out
            prjs = _ncbi_sra_to_bioproject(acc)
            if prjs:
                out["canonical"] = prjs[0]
                out["type"] = "PRJNA"
                out["bioproject"] = prjs[0]
                out["resolver_source"] = "ncbi_bioproject"
                pmids = _ncbi_bioproject_to_pmids(prjs[0])
                if pmids:
                    out["pmid"] = pmids[0]
                    out["citation"] = pmid_to_citation(pmids[0])
                out["resolution_path"].append(f"{acc} -> SRA -> BioProject {prjs[0]}")
                return out
            out["note"] = f"{acc}: no GSE or BioProject linked"
            return out

        if cls["type"] in ("ERX", "ERR"):
            meta = _ebi_ena_metadata(acc)
            bp = meta.get("bioproject")
            if bp:
                out["canonical"] = bp
                out["bioproject"] = bp
                out["type"] = "PRJEB"
                out["resolver_source"] = "ebi_ena"
                pmids = meta.get("pmids", []) or _ncbi_bioproject_to_pmids(bp)
                if pmids:
                    out["pmid"] = pmids[0]
                    out["citation"] = pmid_to_citation(pmids[0])
                out["resolution_path"].append(f"{acc} -> ENA -> BioProject {bp}")
                return out
            out["note"] = f"{acc}: no BioProject linked in ENA"
            return out

        if cls["type"] in ("DRX", "DRR"):
            # DDBJ analysis units — try INSDC BioProject via NCBI bioproject db
            prjs = _ncbi_sra_to_bioproject(acc)
            if prjs:
                out["canonical"] = prjs[0]
                out["bioproject"] = prjs[0]
                out["type"] = "PRJDB" if prjs[0].startswith("PRJDB") else "PRJNA"
                out["resolver_source"] = "ddbj"
                pmids = _ncbi_bioproject_to_pmids(prjs[0])
                if pmids:
                    out["pmid"] = pmids[0]
                    out["citation"] = pmid_to_citation(pmids[0])
                out["resolution_path"].append(f"{acc} -> DDBJ/INSDC -> BioProject {prjs[0]}")
                return out
            out["note"] = f"{acc}: no DDBJ BioProject cross-link"
            return out

        out["note"] = f"{cls['type']} analysis unit — parent study lookup not automated"
        return out

    # -----------------------------------------------------------------
    # Citation units
    # -----------------------------------------------------------------

    # NCBI GEO Series
    if cls["type"] == "GSE":
        rec = _ncbi_geo_series_record(acc)
        out["bioproject"] = rec.get("bioproject")
        pmids = rec.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"GSE {acc} -> !Series_pubmed_id -> PMID {pmids[0]}")
        else:
            out["note"] = "GEO series has no !Series_pubmed_id"
        return out

    # NCBI SRA Study
    if cls["type"] == "SRP":
        gses = _ncbi_sra_to_gse(acc)
        if gses:
            out["canonical"] = gses[0]
            out["type"] = "GSE"
            out["resolver_source"] = "ncbi_geo"
            rec = _ncbi_geo_series_record(gses[0])
            out["bioproject"] = rec.get("bioproject")
            pmids = rec.get("pmids", [])
            if pmids:
                out["pmid"] = pmids[0]
                out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"SRP {acc} -> GSE {gses[0]} (preferred citation unit)")
            return out
        prjs = _ncbi_sra_to_bioproject(acc)
        if prjs:
            out["bioproject"] = prjs[0]
            out["resolution_path"].append(f"SRP {acc} -> BioProject {prjs[0]}")
            pmids = _ncbi_bioproject_to_pmids(prjs[0])
            if pmids:
                out["pmid"] = pmids[0]
                out["citation"] = pmid_to_citation(pmids[0])
                return out
        # Fallback: Europe PMC fulltext search for the SRP string. Catches SRA-only deposits
        # whose BioProject lacks a PubMed link but whose accession appears in a paper's
        # data-availability section. Example: SRP173986 -> La 2019 PeerJ 7:e6938 via PMC6535221.
        ep_pmids = _ebi_europepmc_search_accession(acc)
        if ep_pmids:
            out["pmid"] = ep_pmids[0]
            out["citation"] = pmid_to_citation(ep_pmids[0])
            out["resolution_path"].append(f"SRP {acc} -> Europe PMC fulltext -> PMID {ep_pmids[0]}")
            out["note"] = "Primary paper not confirmed via GEO/BioProject — Europe PMC fulltext first-hit"
            return out
        if prjs:
            out["note"] = "SRA-only deposit — no PubMed link in BioProject or Europe PMC"
        else:
            out["note"] = "SRA study has no linked GSE, BioProject, or Europe PMC match"
        return out

    # NCBI BioProject (PRJNA*)
    if cls["type"] == "PRJNA":
        out["bioproject"] = acc
        pmids = _ncbi_bioproject_to_pmids(acc)
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"PRJNA {acc} -> PubMed link -> PMID {pmids[0]}")
        else:
            out["note"] = "BioProject has no PubMed link"
        return out

    # EBI ENA BioProject + study (PRJEB*, ERP*)
    if cls["type"] in ("PRJEB", "ERP"):
        meta = _ebi_ena_metadata(acc)
        bp = meta.get("bioproject") or (acc if acc.startswith("PRJEB") else None)
        out["bioproject"] = bp
        pmids = meta.get("pmids", []) or (_ncbi_bioproject_to_pmids(bp) if bp else [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"ENA {acc} -> PMID {pmids[0]}")
        else:
            out["note"] = "ENA accession has no linked PubMed"
        return out

    # DDBJ (PRJDB*, DRP*)
    if cls["type"] in ("PRJDB", "DRP"):
        # DDBJ shares BioProject IDs with NCBI INSDC; query eutils bioproject
        bp = acc if acc.startswith("PRJDB") else None
        if not bp:
            prjs = _ncbi_sra_to_bioproject(acc)
            bp = prjs[0] if prjs else None
        if bp:
            out["bioproject"] = bp
            pmids = _ncbi_bioproject_to_pmids(bp)
            if pmids:
                out["pmid"] = pmids[0]
                out["citation"] = pmid_to_citation(pmids[0])
                out["resolution_path"].append(f"DDBJ {acc} -> NCBI BioProject {bp} -> PMID {pmids[0]}")
            else:
                out["note"] = f"DDBJ BioProject {bp} has no PubMed link"
        else:
            out["note"] = "DDBJ accession not found in NCBI BioProject"
        return out

    # EBI ArrayExpress (E-MTAB-*, E-GEOD-*, ...)
    if cls["type"] == "ArrayExpress":
        # Try JSON attributes first (fast but often missing PMID)
        meta = _ebi_biostudies_json_pmids(acc)
        pmids = meta.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"ArrayExpress {acc} -> BioStudies JSON attrs -> PMID {pmids[0]}")
            return out
        # Try IDF text file (MAGE-TAB canonical PMID location)
        idf = _ebi_arrayexpress_idf(acc)
        pmids = idf.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"ArrayExpress {acc} -> IDF PubMed ID -> PMID {pmids[0]}")
            return out
        # Fallback: Europe PMC fulltext search for accession
        ep_pmids = _ebi_europepmc_search_accession(acc)
        if ep_pmids:
            out["pmid"] = ep_pmids[0]
            out["citation"] = pmid_to_citation(ep_pmids[0])
            out["resolution_path"].append(f"ArrayExpress {acc} -> Europe PMC fulltext -> PMID {ep_pmids[0]}")
            out["note"] = "Primary paper not confirmed from BioStudies — Europe PMC first-hit"
            return out
        out["note"] = f"ArrayExpress {acc}: no PubMed link in BioStudies JSON, IDF, or Europe PMC"
        return out

    # EBI BioStudies (S-BSST*, S-EPMC*)
    if cls["type"] == "BioStudies":
        meta = _ebi_biostudies_json_pmids(acc)
        pmids = meta.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"BioStudies {acc} -> attrs -> PMID {pmids[0]}")
        else:
            out["note"] = f"BioStudies {acc}: no PubMed link"
        return out

    # NGDC GSA (CRA*, HRA*, PRJCA*)
    if cls["type"] in ("CRA", "HRA", "PRJCA"):
        meta = _ngdc_gsa_html(acc)
        bp = meta.get("bioproject") or (acc if acc.startswith("PRJCA") else None)
        out["bioproject"] = bp
        pmids = meta.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"NGDC GSA {acc} -> HTML scrape -> PMID {pmids[0]}")
            return out
        # Fallback: Europe PMC
        ep_pmids = _ebi_europepmc_search_accession(acc)
        if ep_pmids:
            out["pmid"] = ep_pmids[0]
            out["citation"] = pmid_to_citation(ep_pmids[0])
            out["resolution_path"].append(f"NGDC GSA {acc} -> Europe PMC fulltext -> PMID {ep_pmids[0]}")
            out["note"] = "Primary paper not confirmed from NGDC — Europe PMC first-hit"
            return out
        out["note"] = f"NGDC GSA {acc}: no PubMed link (HTML or Europe PMC). err={meta.get('error')}"
        return out

    # NGDC OMIX (OMIX*)
    if cls["type"] == "OMIX":
        meta = _ngdc_omix_html(acc)
        bp = meta.get("bioproject")
        out["bioproject"] = bp
        pmids = meta.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"NGDC OMIX {acc} -> HTML -> PMID {pmids[0]}")
            return out
        # Fallback via BioProject cross-link (PRJCA captured from HTML)
        if bp:
            out["resolution_path"].append(f"NGDC OMIX {acc} -> HTML -> BioProject {bp}")
            # Europe PMC fulltext
            ep_pmids = _ebi_europepmc_search_accession(acc) or _ebi_europepmc_search_accession(bp)
            if ep_pmids:
                out["pmid"] = ep_pmids[0]
                out["citation"] = pmid_to_citation(ep_pmids[0])
                out["resolution_path"].append(f"-> Europe PMC fulltext -> PMID {ep_pmids[0]}")
                out["note"] = "Primary paper not confirmed — Europe PMC first-hit"
                return out
            out["note"] = f"NGDC OMIX {acc}: BioProject {bp} known but no PubMed link"
            return out
        out["note"] = f"NGDC OMIX {acc}: HTML gave no BioProject or PubMed"
        return out

    # CNGB (CNP*)
    if cls["type"] == "CNP":
        meta = _cngb_html(acc)
        pmids = meta.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"CNGB {acc} -> HTML -> PMID {pmids[0]}")
            return out
        ep_pmids = _ebi_europepmc_search_accession(acc)
        if ep_pmids:
            out["pmid"] = ep_pmids[0]
            out["citation"] = pmid_to_citation(ep_pmids[0])
            out["resolution_path"].append(f"CNGB {acc} -> Europe PMC fulltext -> PMID {ep_pmids[0]}")
            out["note"] = "Primary paper not confirmed — Europe PMC first-hit"
            return out
        out["note"] = f"CNGB {acc}: no PubMed link (HTML or Europe PMC)"
        return out

    # CNGB CDCP (SCDS*) — single-cell aggregator. HTML shell shares sample GSE/CNP links
    # across pages (false positive risk), so we prefer Europe PMC fulltext which requires
    # the SCDS accession to actually appear in a paper's body text.
    if cls["type"] == "SCDS":
        meta = _cngb_cdcp_html(acc)
        if meta.get("not_found"):
            out["note"] = f"CDCP {acc}: dataset page not found (shell only, no description)"
            return out
        if meta.get("error"):
            out["note"] = f"CDCP {acc}: fetch error {meta['error']}"
            return out
        # Description-local PubMed (rare — most CDCP pages carry prose abstracts, no PMID)
        pmids = meta.get("pmids", [])
        if pmids:
            out["pmid"] = pmids[0]
            out["citation"] = pmid_to_citation(pmids[0])
            out["resolution_path"].append(f"CDCP {acc} -> description PubMed -> PMID {pmids[0]}")
            return out
        # Europe PMC fulltext: SCDS accession must appear in a paper's data-availability
        # section. Strongest available signal.
        ep_pmids = _ebi_europepmc_search_accession(acc)
        if ep_pmids:
            out["pmid"] = ep_pmids[0]
            out["citation"] = pmid_to_citation(ep_pmids[0])
            out["resolution_path"].append(f"CDCP {acc} -> Europe PMC fulltext -> PMID {ep_pmids[0]}")
            out["note"] = "Primary paper not confirmed from CDCP metadata — Europe PMC first-hit"
            return out
        title = (meta.get("title") or "").split(" - ")[0][:60]
        out["note"] = (
            f"CDCP {acc} ({title!r}): no primary paper extractable. "
            f"Upstream cross-links in CDCP page are shared shell content — check the "
            f"Downloads / Citation tab on the CDCP website manually."
        )
        return out

    out["note"] = f"Unhandled citation-unit type {cls['type']}"
    return out


# =====================================================================
# Convenience wrappers
# =====================================================================

def resolve_to_citation(accession: str) -> str:
    """Accession → one-line formal citation string."""
    r = resolve_accession(accession)
    return format_citation(r.get("citation"))


def bulk_resolve(accessions: List[str]) -> List[Dict[str, Any]]:
    """Resolve many accessions (serial; each call is rate-limited by _http)."""
    return [resolve_accession(a) for a in accessions]


# =====================================================================
# Multi-accession cell parser (for dataset tables)
# =====================================================================

_ACC_PATTERN = re.compile(
    r"\b(?:"
    r"GSE\d+|GSM\d+|"
    r"SRP\d+|SRX\d+|SRR\d+|"
    r"ERP\d+|ERX\d+|ERR\d+|"
    r"DRP\d+|DRX\d+|DRR\d+|"
    r"PRJNA\d+|PRJEB\d+|PRJDB\d+|PRJCA\d+|"
    r"E-(?:MTAB|GEOD|PROT|ENAD)-\d+|"
    r"S-(?:BSST|EPMC)\d+|"
    r"CRA\d+|HRA\d+|CRX\d+|CRR\d+|"
    r"OMIX\d+|CNP\d+|CNX\d+|CNR\d+|"
    r"SCDS\d+|"
    r"PMC\d+"
    r")\b",
    re.IGNORECASE,
)


def parse_accession_cell(cell_text: str) -> List[str]:
    """Extract every known-prefix accession from a table cell."""
    if not cell_text:
        return []
    hits = _ACC_PATTERN.findall(cell_text)
    seen = set()
    out: List[str] = []
    for h in hits:
        hu = h.upper()
        if hu not in seen:
            seen.add(hu)
            out.append(h)
    return out


def resolve_cell(cell_text: str) -> List[Dict[str, Any]]:
    """Parse + resolve every accession inside a single cell."""
    return [resolve_accession(a) for a in parse_accession_cell(cell_text)]
