#!/usr/bin/env python3
"""Dataset-focused search for biomedical topics.

Global dataset sources:
- GEO (NCBI GDS)
- SRA (NCBI SRA)
- BioProject (NCBI)
- ArrayExpress/BioStudies (EBI)
- PRIDE (EBI Proteomics)
- ENA (EBI ENA Portal)
- BIGD/GSA (NGDC/CNCB)
- CNGBdb (best-effort public page parsing)
- DDBJ Search (best-effort public page parsing)
- OmicsDI (EBI cross-omics aggregator)
- MetaboLights (EBI metabolomics)
- ProteomeXchange (proteomics umbrella)
- Zenodo (generic scientific data)
- Figshare (generic scientific data)
- Dryad (research data)
- DataCite (DOI registry for data)
- CZ CELLxGENE (single-cell atlas)
- GDC / TCGA (NIH cancer genomics)
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# Allow running as a script from the repo root.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from shawn_bio_search.sources.kaggle import fetch_kaggle_datasets


def _get_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "ignore")


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]{3,}", (text or "").lower()))


def _overlap_ratio(base: str, target: str) -> float:
    a = _tokenize(base)
    b = _tokenize(target)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _year_from_text(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"(19|20)\d{2}", text)
    return int(m.group(0)) if m else None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _infer_assay(text: str) -> str:
    t = (text or "").lower()
    if "scRNA" in text or "single cell" in t:
        return "scRNA-Seq"
    if "rna-seq" in t or "rnaseq" in t:
        return "RNA-Seq"
    if "chip-seq" in t or "chip seq" in t:
        return "ChIP-Seq"
    if "atac-seq" in t or "atac seq" in t:
        return "ATAC-Seq"
    if "wgs" in t or "whole genome" in t:
        return "WGS"
    return ""


def _score_dataset(d: Dict[str, Any], query: str, organism: str, assay: str) -> Dict[str, Any]:
    corpus = " ".join(
        [
            d.get("title", ""),
            d.get("summary", ""),
            d.get("organism", ""),
            d.get("assay", ""),
            d.get("disease", ""),
            d.get("tissue", ""),
        ]
    )

    q_overlap = _overlap_ratio(query, corpus)
    org_overlap = _overlap_ratio(organism, corpus) if organism else 0.0
    assay_overlap = _overlap_ratio(assay, corpus) if assay else 0.0

    completeness = 0.0
    for k in ("accession", "title", "url", "repository"):
        if d.get(k):
            completeness += 0.1
    if d.get("organism"):
        completeness += 0.1
    if d.get("assay"):
        completeness += 0.1

    score = 0.7 * q_overlap + 0.2 * org_overlap + 0.1 * assay_overlap + min(completeness, 0.3)
    d["query_overlap"] = round(q_overlap, 4)
    d["relevance_score"] = round(min(score, 1.0), 4)
    return d


def fetch_geo(query: str, limit: int) -> List[Dict[str, Any]]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    esearch = _get_json(
        f"{base}/esearch.fcgi?"
        + urllib.parse.urlencode({"db": "gds", "term": query, "retmode": "json", "retmax": str(limit), "sort": "relevance"})
    )
    ids = esearch.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    summary = _get_json(
        f"{base}/esummary.fcgi?" + urllib.parse.urlencode({"db": "gds", "id": ",".join(ids), "retmode": "json"})
    ).get("result", {})

    out = []
    for gid in ids:
        doc = summary.get(gid) or {}
        accession = doc.get("accession")
        if not accession:
            continue
        out.append(
            {
                "repository": "geo",
                "accession": accession,
                "title": doc.get("title") or "",
                "organism": doc.get("taxon") or "",
                "assay": doc.get("gdstype") or "",
                "sample_count": doc.get("n_samples"),
                "disease": "",
                "tissue": "",
                "summary": doc.get("summary") or "",
                "year": _year_from_text(doc.get("pd") or ""),
                "raw_available": None,
                "processed_available": True,
                "url": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}",
            }
        )
    return out


def _extract_exp_field(expxml: str, pattern: str) -> str:
    m = re.search(pattern, expxml)
    return m.group(1).strip() if m else ""


def fetch_sra(query: str, limit: int) -> List[Dict[str, Any]]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    esearch = _get_json(
        f"{base}/esearch.fcgi?"
        + urllib.parse.urlencode({"db": "sra", "term": query, "retmode": "json", "retmax": str(limit), "sort": "relevance"})
    )
    ids = esearch.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    xml_text = _get_text(
        f"{base}/efetch.fcgi?"
        + urllib.parse.urlencode({"db": "sra", "id": ",".join(ids), "rettype": "docsum", "retmode": "xml"})
    )

    root = ET.fromstring(xml_text)
    out = []
    for docsum in root.findall(".//DocSum"):
        expxml_item = None
        for item in docsum.findall("Item"):
            if item.attrib.get("Name") == "ExpXml":
                expxml_item = item
                break
        if expxml_item is None or expxml_item.text is None:
            continue

        exp = html.unescape(expxml_item.text)
        title = _extract_exp_field(exp, r"<Title>(.*?)</Title>")
        study_acc = _extract_exp_field(exp, r"<Study acc=\"(SRP\d+)\"")
        sample_acc = _extract_exp_field(exp, r"<Sample acc=\"(SRS\d+)\"")
        organism = _extract_exp_field(exp, r"ScientificName=\"(.*?)\"")
        assay = _extract_exp_field(exp, r"<LIBRARY_STRATEGY>(.*?)</LIBRARY_STRATEGY>")
        accession = study_acc or sample_acc or docsum.findtext("Id", default="")

        out.append(
            {
                "repository": "sra",
                "accession": accession,
                "title": title,
                "organism": organism,
                "assay": assay,
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": title,
                "year": None,
                "raw_available": True,
                "processed_available": None,
                "url": f"https://www.ncbi.nlm.nih.gov/sra/?term={urllib.parse.quote(accession)}" if accession else "",
            }
        )
    return out


def fetch_bioproject(query: str, limit: int) -> List[Dict[str, Any]]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    esearch = _get_json(
        f"{base}/esearch.fcgi?"
        + urllib.parse.urlencode({"db": "bioproject", "term": query, "retmode": "json", "retmax": str(limit), "sort": "relevance"})
    )
    ids = esearch.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    summary = _get_json(
        f"{base}/esummary.fcgi?"
        + urllib.parse.urlencode({"db": "bioproject", "id": ",".join(ids), "retmode": "json"})
    ).get("result", {})

    out = []
    for bid in ids:
        doc = summary.get(bid) or {}
        acc = doc.get("project_acc") or bid
        title = doc.get("project_title") or doc.get("project_description") or ""
        out.append(
            {
                "repository": "bioproject",
                "accession": acc,
                "title": title,
                "organism": doc.get("organism_name") or "",
                "assay": doc.get("project_data_type") or "",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": doc.get("project_description") or "",
                "year": _year_from_text(doc.get("registration_date") or ""),
                "raw_available": True,
                "processed_available": None,
                "url": f"https://www.ncbi.nlm.nih.gov/bioproject/{acc}",
            }
        )
    return out


def fetch_arrayexpress(query: str, limit: int) -> List[Dict[str, Any]]:
    params = {"query": query, "page": "1", "pageSize": str(max(1, min(limit, 100))), "sortBy": "relevance", "sortOrder": "descending"}
    data = _get_json("https://www.ebi.ac.uk/biostudies/api/v1/search?" + urllib.parse.urlencode(params))

    out = []
    for h in data.get("hits", []):
        acc = h.get("accession") or ""
        if not (acc.startswith("E-") or acc.startswith("A-")):
            continue
        out.append(
            {
                "repository": "arrayexpress",
                "accession": acc,
                "title": h.get("title") or "",
                "organism": "",
                "assay": "",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": (h.get("content") or "")[:500],
                "year": _year_from_text(h.get("release_date") or ""),
                "raw_available": None,
                "processed_available": None,
                "url": f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{acc}",
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_pride(query: str, limit: int) -> List[Dict[str, Any]]:
    params = {"keyword": query, "pageSize": str(max(1, min(limit, 100))), "page": "0"}
    rows = _get_json("https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects?" + urllib.parse.urlencode(params))

    out = []
    for r in rows[:limit]:
        acc = r.get("accession") or ""
        orgs = r.get("organisms") or []
        organism = ", ".join([o.get("name") for o in orgs if isinstance(o, dict) and o.get("name")])
        exp_types = r.get("experimentTypes") or []
        assay = ", ".join([e.get("name") for e in exp_types if isinstance(e, dict) and e.get("name")])
        out.append(
            {
                "repository": "pride",
                "accession": acc,
                "title": r.get("title") or "",
                "organism": organism,
                "assay": assay,
                "sample_count": None,
                "disease": ", ".join(r.get("diseases") or []),
                "tissue": "",
                "summary": r.get("projectDescription") or "",
                "year": _year_from_text(r.get("publicationDate") or ""),
                "raw_available": True,
                "processed_available": None,
                "url": f"https://www.ebi.ac.uk/pride/archive/projects/{acc}" if acc else "",
            }
        )
    return out


def fetch_ena(query: str, limit: int) -> List[Dict[str, Any]]:
    # ENA requires field-based query syntax and valid field names.
    q = f'study_title="{query}"'
    fields = "study_accession,study_title,scientific_name,center_name,first_public,last_updated"
    params = {"result": "study", "query": q, "fields": fields, "format": "json", "limit": str(max(1, min(limit, 100)))}
    rows = _get_json("https://www.ebi.ac.uk/ena/portal/api/search?" + urllib.parse.urlencode(params))

    out = []
    for r in rows[:limit]:
        acc = r.get("study_accession") or ""
        title = r.get("study_title") or ""
        out.append(
            {
                "repository": "ena",
                "accession": acc,
                "title": title,
                "organism": r.get("scientific_name") or "",
                "assay": _infer_assay(title),
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": title,
                "year": _year_from_text(r.get("first_public") or r.get("last_updated") or ""),
                "raw_available": True,
                "processed_available": None,
                "url": f"https://www.ebi.ac.uk/ena/browser/view/{acc}" if acc else "",
            }
        )
    return out


def fetch_bigd(query: str, limit: int) -> List[Dict[str, Any]]:
    # BIGD GSA search page renders result_area blocks server-side.
    url = "https://bigd.big.ac.cn/gsa/search?" + urllib.parse.urlencode({"keyword": query})
    html_text = _get_text(url, headers={"User-Agent": "Mozilla/5.0"})
    blocks = html_text.split('<div class="result_area">')[1:]

    out = []
    for b in blocks:
        acc = ""
        checkbox = re.search(r'class="checkbox_class"[^>]*data-value="([A-Z]{2,6}\d+)"', b)
        if checkbox:
            acc = checkbox.group(1)

        link_match = re.search(r'href="(https?://[^"]*/gsa/browse/[^"]+)"', b)
        title_match = re.search(r'<span class="result_title">\s*Title:\s*</span>\s*<span class="result_context">([\s\S]*?)</span>', b)
        strategy_match = re.search(r'<span class="result_title">\s*Strategy name:\s*</span>\s*<span class="result_context">([\s\S]*?)</span>', b)

        if not acc and not link_match:
            continue

        link = link_match.group(1) if link_match else ""
        title = _strip_tags(title_match.group(1)) if title_match else ""
        strategy = _strip_tags(strategy_match.group(1)) if strategy_match else ""
        parts = [x.strip() for x in title.split(";") if x.strip()]
        organism = parts[-2] if len(parts) >= 2 else ""
        assay = strategy or (parts[-1] if len(parts) >= 1 else _infer_assay(title))

        out.append(
            {
                "repository": "bigd",
                "accession": acc,
                "title": title,
                "organism": organism,
                "assay": assay,
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": title,
                "year": None,
                "raw_available": True,
                "processed_available": None,
                "url": link if link.startswith("http") else f"https://bigd.big.ac.cn{link}",
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_cngb(query: str, limit: int) -> List[Dict[str, Any]]:
    # CNGBdb is JS-driven with AJAX endpoints that may throttle (429) or reject params.
    # Try a minimal parameter set first, then fallback to page-level accession extraction.
    endpoint = "https://db.cngb.org/search/ajax/global_result/"
    payload = None
    for params in [
        {"keyword": query, "page": 1, "page_size": max(1, min(limit, 50))},
        {"q": query, "page": 1, "page_size": max(1, min(limit, 50))},
    ]:
        url = endpoint + "?" + urllib.parse.urlencode(params)
        try:
            payload = _get_json(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            if isinstance(payload, dict) and payload.get("code") == 2:
                payload = None
                continue
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                return []
            continue
        except Exception:
            continue

    out: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        container = payload.get("data") or payload.get("result") or payload.get("results") or payload.get("items")
        records: List[Dict[str, Any]] = []
        if isinstance(container, list):
            records = [x for x in container if isinstance(x, dict)]
        elif isinstance(container, dict):
            for k in ("list", "items", "results", "records"):
                v = container.get(k)
                if isinstance(v, list):
                    records = [x for x in v if isinstance(x, dict)]
                    break

        for r in records:
            accession = str(
                r.get("accession")
                or r.get("identifier")
                or r.get("project_accession")
                or r.get("experiment_accession")
                or ""
            )
            if not re.match(r"^(CNSA\d+|CNP\d+|CNX\d+|CRA\d+|PRJCA\d+)$", accession):
                continue
            title = str(r.get("title") or r.get("name") or "")
            out.append(
                {
                    "repository": "cngb",
                    "accession": accession,
                    "title": title or f"CNGBdb accession {accession}",
                    "organism": str(r.get("organism") or ""),
                    "assay": str(r.get("assay") or r.get("data_type") or _infer_assay(title)),
                    "sample_count": None,
                    "disease": "",
                    "tissue": "",
                    "summary": title,
                    "year": _year_from_text(str(r.get("release_date") or r.get("updated_at") or "")),
                    "raw_available": None,
                    "processed_available": None,
                    "url": f"https://db.cngb.org/search/?q={urllib.parse.quote(accession)}",
                }
            )
            if len(out) >= limit:
                return out

    # Fallback: extract any visible accessions from public HTML.
    url = "https://db.cngb.org/search/?" + urllib.parse.urlencode({"q": query})
    html_text = _get_text(url, headers={"User-Agent": "Mozilla/5.0"})
    accs: List[str] = []
    for pat in [r"CNSA\d+", r"CNP\d+", r"CNX\d+", r"CRA\d+", r"PRJCA\d+"]:
        accs.extend(re.findall(pat, html_text))

    uniq = []
    seen = set()
    for a in accs:
        if a in seen:
            continue
        seen.add(a)
        uniq.append(a)

    out = out[:]
    for acc in uniq[:limit]:
        if any(x.get("accession") == acc for x in out):
            continue
        out.append(
            {
                "repository": "cngb",
                "accession": acc,
                "title": f"CNGBdb accession {acc}",
                "organism": "",
                "assay": "",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": "",
                "year": None,
                "raw_available": None,
                "processed_available": None,
                "url": f"https://db.cngb.org/search/?q={urllib.parse.quote(acc)}",
            }
        )
    return out


def fetch_ddbj(query: str, limit: int) -> List[Dict[str, Any]]:
    # DDBJ search UI is JS-driven; direct resource search API may be restricted.
    # Best-effort extraction from public pages and known accession patterns.
    html_text = ""
    for url in [
        "https://ddbj.nig.ac.jp/search?" + urllib.parse.urlencode({"query": query}),
        "https://ddbj.nig.ac.jp/resource/sra-study?" + urllib.parse.urlencode({"query": query}),
        "https://ddbj.nig.ac.jp/resource/sra-run?" + urllib.parse.urlencode({"query": query}),
    ]:
        try:
            html_text += "\n" + _get_text(url, headers={"User-Agent": "Mozilla/5.0"})
        except Exception:
            continue

    accs = []
    for pat in [r"DRA\d+", r"DRP\d+", r"DRX\d+", r"DRS\d+"]:
        accs.extend(re.findall(pat, html_text))

    uniq = []
    seen = set()
    for a in accs:
        if a in seen:
            continue
        seen.add(a)
        uniq.append(a)

    out = []
    for acc in uniq[:limit]:
        out.append(
            {
                "repository": "ddbj",
                "accession": acc,
                "title": f"DDBJ accession {acc}",
                "organism": "",
                "assay": "",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": "",
                "year": None,
                "raw_available": None,
                "processed_available": None,
                "url": f"https://ddbj.nig.ac.jp/search?query={urllib.parse.quote(acc)}",
            }
        )
    return out


def fetch_omicsdi(query: str, limit: int) -> List[Dict[str, Any]]:
    """OmicsDI: cross-omics aggregator (EBI). Returns entries from GEO, PRIDE,
    MetaboLights, ArrayExpress, and many others unified in one search."""
    params = {"query": query, "size": str(max(1, min(limit, 100))), "start": "0"}
    url = "https://www.omicsdi.org/ws/dataset/search?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    out = []
    for d in (data.get("datasets") or [])[:limit]:
        acc = d.get("id") or ""
        repo = (d.get("source") or d.get("database") or "omicsdi").lower()
        title = d.get("title") or ""
        description = d.get("description") or ""
        organisms = d.get("organism") or d.get("organisms") or []
        if isinstance(organisms, list):
            organism = ", ".join([str(o) for o in organisms if o])
        else:
            organism = str(organisms)
        out.append(
            {
                "repository": f"omicsdi:{repo}",
                "accession": acc,
                "title": title,
                "organism": organism,
                "assay": d.get("omics_type") or d.get("omicsType") or "",
                "sample_count": None,
                "disease": ", ".join(d.get("diseases") or []) if isinstance(d.get("diseases"), list) else "",
                "tissue": ", ".join(d.get("tissues") or []) if isinstance(d.get("tissues"), list) else "",
                "summary": description or title,
                "year": _year_from_text(str(d.get("publicationDate") or d.get("submissionDate") or "")),
                "raw_available": None,
                "processed_available": None,
                "url": f"https://www.omicsdi.org/dataset/{repo}/{acc}" if acc else "https://www.omicsdi.org/",
            }
        )
    return out


def fetch_metabolights(query: str, limit: int) -> List[Dict[str, Any]]:
    """MetaboLights: metabolomics studies (EBI)."""
    url = "https://www.ebi.ac.uk/metabolights/ws/studies/public/search?" + urllib.parse.urlencode({"query": query})
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    rows = data.get("content") or data.get("studies") or []
    if isinstance(rows, dict):
        rows = rows.get("studies") or []
    out = []
    for r in rows[:limit]:
        acc = r.get("accession") or r.get("studyIdentifier") or ""
        title = r.get("title") or ""
        organism = r.get("organism") or ""
        if isinstance(organism, list):
            organism = ", ".join([str(o) for o in organism if o])
        out.append(
            {
                "repository": "metabolights",
                "accession": acc,
                "title": title,
                "organism": str(organism or ""),
                "assay": "metabolomics",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": r.get("description") or title,
                "year": _year_from_text(str(r.get("publicDate") or r.get("submissionDate") or "")),
                "raw_available": True,
                "processed_available": True,
                "url": f"https://www.ebi.ac.uk/metabolights/{acc}" if acc else "",
            }
        )
    return out


def fetch_proteomexchange(query: str, limit: int) -> List[Dict[str, Any]]:
    """ProteomeXchange: proteomics umbrella (PRIDE, MassIVE, jPOST, iProX, Panorama)."""
    url = "https://proteomecentral.proteomexchange.org/api/proxi/v0.1/datasets?" + urllib.parse.urlencode(
        {"searchTerms": query, "pageSize": str(max(1, min(limit, 100))), "pageNumber": "1"}
    )
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    rows = data if isinstance(data, list) else data.get("datasets") or []
    out = []
    for r in rows[:limit]:
        acc = r.get("identifier") or r.get("accession") or ""
        title = r.get("title") or ""
        species = r.get("species") or []
        organism = ""
        if isinstance(species, list):
            names = []
            for sp in species:
                if isinstance(sp, dict):
                    names.append(sp.get("name") or sp.get("accession") or "")
                elif sp:
                    names.append(str(sp))
            organism = ", ".join([n for n in names if n])
        out.append(
            {
                "repository": "proteomexchange",
                "accession": acc,
                "title": title,
                "organism": organism,
                "assay": "proteomics",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": r.get("summary") or title,
                "year": _year_from_text(str(r.get("announceDate") or r.get("publicReleaseDate") or "")),
                "raw_available": True,
                "processed_available": None,
                "url": f"https://proteomecentral.proteomexchange.org/cgi/GetDataset?ID={acc}" if acc else "",
            }
        )
    return out


def fetch_zenodo(query: str, limit: int) -> List[Dict[str, Any]]:
    """Zenodo: generic open-science data/software. Filter by type=dataset."""
    params = {
        "q": query,
        "size": str(max(1, min(limit, 100))),
        "type": "dataset",
        "sort": "bestmatch",
    }
    token = __import__("os").getenv("ZENODO_TOKEN")
    if token:
        params["access_token"] = token
    url = "https://zenodo.org/api/records?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    out = []
    for h in (data.get("hits", {}).get("hits") or [])[:limit]:
        metadata = h.get("metadata") or {}
        acc = str(h.get("id") or "")
        doi = metadata.get("doi") or ""
        title = metadata.get("title") or ""
        description = _strip_tags(metadata.get("description") or "")
        out.append(
            {
                "repository": "zenodo",
                "accession": doi or acc,
                "title": title,
                "organism": "",
                "assay": _infer_assay(title + " " + description),
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": description[:500],
                "year": _year_from_text(str(metadata.get("publication_date") or "")),
                "raw_available": True,
                "processed_available": None,
                "url": h.get("links", {}).get("html") or (f"https://doi.org/{doi}" if doi else ""),
            }
        )
    return out


def fetch_figshare(query: str, limit: int) -> List[Dict[str, Any]]:
    """Figshare: generic scientific data. Uses POST-style JSON search."""
    body = json.dumps({"search_for": query, "item_type": 3, "page_size": max(1, min(limit, 100))}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.figshare.com/v2/articles/search",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    out = []
    for r in (rows or [])[:limit]:
        doi = r.get("doi") or ""
        acc = str(r.get("id") or doi)
        title = r.get("title") or ""
        out.append(
            {
                "repository": "figshare",
                "accession": acc,
                "title": title,
                "organism": "",
                "assay": _infer_assay(title),
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": title,
                "year": _year_from_text(str(r.get("published_date") or r.get("timeline", {}).get("firstOnline") or "")),
                "raw_available": True,
                "processed_available": None,
                "url": r.get("url_public_html") or r.get("url") or (f"https://doi.org/{doi}" if doi else ""),
            }
        )
    return out


def fetch_dryad(query: str, limit: int) -> List[Dict[str, Any]]:
    """Dryad: data publishing platform."""
    params = {"q": query, "per_page": str(max(1, min(limit, 100))), "page": "1"}
    url = "https://datadryad.org/api/v2/search?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    rows = (data.get("_embedded") or {}).get("stash:datasets") or data.get("datasets") or []
    out = []
    for r in rows[:limit]:
        doi = r.get("identifier") or r.get("doi") or ""
        title = r.get("title") or ""
        description = _strip_tags(r.get("abstract") or "")
        out.append(
            {
                "repository": "dryad",
                "accession": doi,
                "title": title,
                "organism": "",
                "assay": _infer_assay(title + " " + description),
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": description[:500],
                "year": _year_from_text(str(r.get("publicationDate") or r.get("lastModificationDate") or "")),
                "raw_available": True,
                "processed_available": None,
                "url": f"https://doi.org/{doi.lstrip('doi:')}" if doi else "",
            }
        )
    return out


def fetch_datacite(query: str, limit: int) -> List[Dict[str, Any]]:
    """DataCite: DOI registry for research data. Filter resource-type to Dataset."""
    params = {
        "query": query,
        "resource-type-id": "dataset",
        "page[size]": str(max(1, min(limit, 100))),
    }
    url = "https://api.datacite.org/dois?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, headers={"Accept": "application/vnd.api+json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    out = []
    for d in (data.get("data") or [])[:limit]:
        attrs = d.get("attributes") or {}
        doi = attrs.get("doi") or ""
        titles = attrs.get("titles") or []
        title = titles[0].get("title") if titles and isinstance(titles[0], dict) else ""
        descriptions = attrs.get("descriptions") or []
        description = descriptions[0].get("description") if descriptions and isinstance(descriptions[0], dict) else ""
        subjects = attrs.get("subjects") or []
        subj_texts = [s.get("subject") for s in subjects if isinstance(s, dict) and s.get("subject")]
        out.append(
            {
                "repository": "datacite",
                "accession": doi,
                "title": title or "",
                "organism": "",
                "assay": _infer_assay((title or "") + " " + " ".join(subj_texts)),
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": _strip_tags(description or "")[:500],
                "year": int(attrs.get("publicationYear")) if attrs.get("publicationYear") else None,
                "raw_available": True,
                "processed_available": None,
                "url": attrs.get("url") or (f"https://doi.org/{doi}" if doi else ""),
            }
        )
    return out


def fetch_cellxgene(query: str, limit: int) -> List[Dict[str, Any]]:
    """CZ CELLxGENE: human/mouse single-cell datasets.

    Uses the Census-Discover collections endpoint and filters client-side by
    matching query tokens against title/description/organism.
    """
    url = "https://api.cellxgene.cziscience.com/curation/v1/collections"
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    qtoks = _tokenize(query)
    out = []
    for c in data or []:
        title = c.get("name") or ""
        description = c.get("description") or ""
        orgs = c.get("organisms") or []
        if isinstance(orgs, list):
            organism = ", ".join([o.get("label") if isinstance(o, dict) else str(o) for o in orgs])
        else:
            organism = str(orgs or "")
        corpus = f"{title} {description} {organism}".lower()
        if qtoks and not (qtoks & _tokenize(corpus)):
            continue
        acc = c.get("collection_id") or c.get("id") or ""
        out.append(
            {
                "repository": "cellxgene",
                "accession": acc,
                "title": title,
                "organism": organism,
                "assay": "scRNA-Seq",
                "sample_count": None,
                "disease": "",
                "tissue": "",
                "summary": description[:500],
                "year": _year_from_text(str(c.get("published_at") or c.get("created_at") or "")),
                "raw_available": True,
                "processed_available": True,
                "url": f"https://cellxgene.cziscience.com/collections/{acc}" if acc else "https://cellxgene.cziscience.com/",
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_gdc(query: str, limit: int) -> List[Dict[str, Any]]:
    """NIH GDC (TCGA and other cancer programs). Searches projects."""
    filters = json.dumps(
        {
            "op": "or",
            "content": [
                {"op": "match", "content": {"field": "name", "value": query}},
                {"op": "match", "content": {"field": "project_id", "value": query}},
                {"op": "match", "content": {"field": "primary_site", "value": query}},
                {"op": "match", "content": {"field": "disease_type", "value": query}},
            ],
        }
    )
    params = {
        "filters": filters,
        "size": str(max(1, min(limit, 100))),
        "fields": "project_id,name,primary_site,disease_type,program.name,summary.case_count,released",
        "format": "json",
    }
    url = "https://api.gdc.cancer.gov/projects?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    except Exception:
        return []

    out = []
    for h in (data.get("data", {}).get("hits") or [])[:limit]:
        pid = h.get("project_id") or ""
        name = h.get("name") or pid
        diseases = h.get("disease_type") or []
        sites = h.get("primary_site") or []
        case_count = (h.get("summary") or {}).get("case_count")
        out.append(
            {
                "repository": "gdc",
                "accession": pid,
                "title": name,
                "organism": "Homo sapiens",
                "assay": "cancer genomics",
                "sample_count": case_count,
                "disease": ", ".join(diseases) if isinstance(diseases, list) else str(diseases),
                "tissue": ", ".join(sites) if isinstance(sites, list) else str(sites),
                "summary": name,
                "year": None,
                "raw_available": True,
                "processed_available": True,
                "url": f"https://portal.gdc.cancer.gov/projects/{pid}" if pid else "https://portal.gdc.cancer.gov/",
            }
        )
    return out


def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        key = (it.get("repository"), it.get("accession"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Dataset-focused search for global sources")
    parser.add_argument("--query", required=True)
    parser.add_argument("--organism", default="")
    parser.add_argument("--assay", default="")
    parser.add_argument("--max-per-source", type=int, default=20)
    parser.add_argument("--no-geo", action="store_true")
    parser.add_argument("--no-sra", action="store_true")
    parser.add_argument("--no-bioproject", action="store_true")
    parser.add_argument("--no-arrayexpress", action="store_true")
    parser.add_argument("--no-pride", action="store_true")
    parser.add_argument("--no-ena", action="store_true")
    parser.add_argument("--no-bigd", action="store_true")
    parser.add_argument("--no-cngb", action="store_true")
    parser.add_argument("--no-ddbj", action="store_true")
    parser.add_argument("--no-omicsdi", action="store_true")
    parser.add_argument("--no-metabolights", action="store_true")
    parser.add_argument("--no-proteomexchange", action="store_true")
    parser.add_argument("--no-zenodo", action="store_true")
    parser.add_argument("--no-figshare", action="store_true")
    parser.add_argument("--no-dryad", action="store_true")
    parser.add_argument("--no-datacite", action="store_true")
    parser.add_argument("--no-cellxgene", action="store_true")
    parser.add_argument("--no-gdc", action="store_true")
    parser.add_argument("--no-kaggle", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    datasets: List[Dict[str, Any]] = []
    warnings: List[str] = []

    if not args.no_geo:
        try:
            datasets.extend(fetch_geo(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"geo failed: {exc}")

    if not args.no_sra:
        try:
            datasets.extend(fetch_sra(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"sra failed: {exc}")

    if not args.no_bioproject:
        try:
            datasets.extend(fetch_bioproject(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"bioproject failed: {exc}")

    if not args.no_arrayexpress:
        try:
            datasets.extend(fetch_arrayexpress(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"arrayexpress failed: {exc}")

    if not args.no_pride:
        try:
            datasets.extend(fetch_pride(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"pride failed: {exc}")

    if not args.no_ena:
        try:
            datasets.extend(fetch_ena(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"ena failed: {exc}")

    if not args.no_bigd:
        try:
            datasets.extend(fetch_bigd(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"bigd failed: {exc}")

    if not args.no_cngb:
        try:
            got = fetch_cngb(args.query, args.max_per_source)
            if not got:
                warnings.append("cngb returned no parsable public records")
            datasets.extend(got)
        except Exception as exc:
            warnings.append(f"cngb failed: {exc}")

    if not args.no_ddbj:
        try:
            got = fetch_ddbj(args.query, args.max_per_source)
            if not got:
                warnings.append("ddbj returned no parsable public records")
            datasets.extend(got)
        except Exception as exc:
            warnings.append(f"ddbj failed: {exc}")

    if not args.no_omicsdi:
        try:
            datasets.extend(fetch_omicsdi(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"omicsdi failed: {exc}")

    if not args.no_metabolights:
        try:
            datasets.extend(fetch_metabolights(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"metabolights failed: {exc}")

    if not args.no_proteomexchange:
        try:
            datasets.extend(fetch_proteomexchange(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"proteomexchange failed: {exc}")

    if not args.no_zenodo:
        try:
            datasets.extend(fetch_zenodo(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"zenodo failed: {exc}")

    if not args.no_figshare:
        try:
            datasets.extend(fetch_figshare(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"figshare failed: {exc}")

    if not args.no_dryad:
        try:
            datasets.extend(fetch_dryad(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"dryad failed: {exc}")

    if not args.no_datacite:
        try:
            datasets.extend(fetch_datacite(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"datacite failed: {exc}")

    if not args.no_cellxgene:
        try:
            datasets.extend(fetch_cellxgene(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"cellxgene failed: {exc}")

    if not args.no_gdc:
        try:
            datasets.extend(fetch_gdc(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"gdc failed: {exc}")

    if not args.no_kaggle:
        try:
            datasets.extend(fetch_kaggle_datasets(args.query, args.max_per_source))
        except Exception as exc:
            warnings.append(f"kaggle failed: {exc}")

    datasets = dedupe(datasets)
    scored = [_score_dataset(d, args.query, args.organism, args.assay) for d in datasets]
    scored.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)

    result = {
        "query": args.query,
        "organism": args.organism,
        "assay": args.assay,
        "count": len(scored),
        "warnings": warnings,
        "datasets": scored,
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"saved: {args.out}")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
