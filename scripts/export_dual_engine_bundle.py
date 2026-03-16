#!/usr/bin/env python3
"""Export SHawn-bio-search results into dual-engine handoff artifacts.

This keeps retrieval outputs standardized for SHawn-academic-research ingestion.
During transition, legacy evidence-candidate export is kept for compatibility,
while preferred outputs move toward retrieval/access/local-library artifacts.
"""

import argparse
import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _citation_key(p: Dict[str, Any], idx: int) -> str:
    doi = (p.get("doi") or "").strip()
    if doi:
        return doi.replace("/", "_")
    title = (p.get("title") or "paper").strip().replace(" ", "_")[:40]
    year = str(p.get("year") or "nd")
    return f"{year}_{title}_{idx}"


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _http_json(url: str, timeout: int = 12) -> Dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SHawn-bio-search/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        return json.loads(data.decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _pdf_reachable(url: str, timeout: int = 10) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SHawn-bio-search/1.0"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            final_url = r.geturl().lower()
            if "pdf" in ctype or final_url.endswith(".pdf") or "/pdf" in final_url:
                return True
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SHawn-bio-search/1.0", "Range": "bytes=0-1024"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            final_url = r.geturl().lower()
            if "pdf" in ctype or final_url.endswith(".pdf") or "/pdf" in final_url:
                return True
    except Exception:
        return False
    return False


def _fetch_unpaywall(doi: str, email: str, cache: Dict[str, Any]) -> Dict[str, Any]:
    key = (doi or "").strip().lower()
    if not key or not email:
        return {}
    if key not in cache:
        url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
        cache[key] = _http_json(url) or {}
        time.sleep(0.05)
    return cache[key]


def _guess_access(p: Dict[str, Any], unpaywall_email: str = "", unpaywall_cache: Dict[str, Any] | None = None) -> Dict[str, Any]:
    unpaywall_cache = unpaywall_cache or {}
    pdf_url = (
        p.get("oa_pdf_url")
        or p.get("pdf_url")
        or ""
    )
    url = p.get("url") or ""
    source = (p.get("source") or "").lower()
    is_oa = p.get("is_oa")
    oa_status = (p.get("oa_status") or "").lower()
    license_name = p.get("oa_license") or ""
    check_method = "heuristic"

    doi = (p.get("doi") or "").strip()
    if doi and unpaywall_email and (not oa_status and not pdf_url):
        uw = _fetch_unpaywall(doi, unpaywall_email, unpaywall_cache)
        if uw:
            oa_status = (uw.get("oa_status") or "").lower()
            is_oa = uw.get("is_oa")
            best = uw.get("best_oa_location") or {}
            pdf_url = pdf_url or best.get("url_for_pdf") or best.get("url") or ""
            license_name = license_name or best.get("license") or ""
            check_method = "unpaywall"

    status = "unknown"
    downloadable = False
    pdf_reachable = False

    if source in {"biorxiv", "medrxiv"}:
        status = "open"
        downloadable = bool(url or pdf_url)
        pdf_reachable = _pdf_reachable(pdf_url or url)
        check_method = source
    elif source == "clinicaltrials":
        status = "open"
        downloadable = False
        pdf_reachable = False
        check_method = source
    elif oa_status in {"gold", "green", "bronze", "hybrid", "open"} or is_oa is True:
        status = "open"
        downloadable = bool(pdf_url or url)
        pdf_reachable = _pdf_reachable(pdf_url)
        check_method = check_method if check_method != "heuristic" else "oa_metadata"
    elif pdf_url:
        status = "open"
        downloadable = True
        pdf_reachable = _pdf_reachable(pdf_url)
        check_method = "pdf_url"
    elif source == "pubmed":
        status = "unknown"
        downloadable = False
        pdf_reachable = False
        check_method = check_method if check_method != "heuristic" else "pubmed_metadata"
    elif url:
        status = "unknown"
        downloadable = False
        pdf_reachable = False
        check_method = check_method if check_method != "heuristic" else "landing_page_only"

    return {
        "status": status,
        "downloadable": downloadable,
        "pdf_reachable": pdf_reachable,
        "check_method": check_method,
        "pdf_url": pdf_url,
        "license": license_name,
        "notes": "",
    }


def _lookup_local_library(p: Dict[str, Any], pdf_files: List[Path]) -> Dict[str, Any]:
    doi = (p.get("doi") or "").strip()
    pmid = str(p.get("pmid") or "").strip()
    pmcid = str(p.get("pmcid") or "").strip()
    title = (p.get("title") or "").strip()

    doi_tok = _normalize_text(doi)
    pmid_tok = _normalize_text(pmid)
    pmcid_tok = _normalize_text(pmcid)
    title_tok = _normalize_text(title)[:80]

    for path in pdf_files:
        stem = _normalize_text(path.stem)
        if doi_tok and doi_tok in stem:
            return {
                "found": True,
                "match_type": "doi",
                "zotero_key": "",
                "local_pdf_path": str(path),
                "notes": "filename heuristic",
            }
        if pmid_tok and pmid_tok in stem:
            return {
                "found": True,
                "match_type": "pmid",
                "zotero_key": "",
                "local_pdf_path": str(path),
                "notes": "filename heuristic",
            }
        if pmcid_tok and pmcid_tok in stem:
            return {
                "found": True,
                "match_type": "pmcid",
                "zotero_key": "",
                "local_pdf_path": str(path),
                "notes": "filename heuristic",
            }
        if title_tok and len(title_tok) >= 24 and title_tok[:24] in stem:
            return {
                "found": True,
                "match_type": "title_fuzzy",
                "zotero_key": "",
                "local_pdf_path": str(path),
                "notes": "filename heuristic",
            }

    return {
        "found": False,
        "match_type": "",
        "zotero_key": "",
        "local_pdf_path": "",
        "notes": "",
    }


def _normalize_result(
    p: Dict[str, Any],
    idx: int,
    pdf_files: List[Path],
    unpaywall_email: str = "",
    unpaywall_cache: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    access = _guess_access(p, unpaywall_email=unpaywall_email, unpaywall_cache=unpaywall_cache)
    local_library = _lookup_local_library(p, pdf_files) if pdf_files else {
        "found": False,
        "match_type": "",
        "zotero_key": "",
        "local_pdf_path": "",
        "notes": "local lookup not configured",
    }
    source_hits = p.get("source_hits") or ([p.get("source")] if p.get("source") else [])
    source_ids = p.get("source_ids") or ([p.get("id")] if p.get("id") else [])
    return {
        "citation_key": _citation_key(p, idx),
        "source": p.get("source"),
        "source_hits": source_hits,
        "source_ids": source_ids,
        "title": p.get("title"),
        "authors": p.get("authors") or [],
        "year": p.get("year"),
        "doi": p.get("doi"),
        "pmid": p.get("pmid"),
        "pmcid": p.get("pmcid"),
        "url": p.get("url"),
        "abstract": p.get("abstract") or "",
        "access": access,
        "local_path": local_library.get("local_pdf_path") or p.get("local_path"),
        "zotero_match": local_library.get("found"),
        "local_library": local_library,
        "retrieval_rank": idx,
        "retrieval_score": p.get("evidence_score") if p.get("evidence_score") is not None else p.get("stage1_score"),
    }


def _build_search_results(bundle: Dict[str, Any], project: str = "", zotero_root: str = "", unpaywall_email: str = "") -> Dict[str, Any]:
    paper_block = bundle.get("papers") or {}
    papers: List[Dict[str, Any]] = paper_block.get("papers") or []
    pdf_files = list(Path(zotero_root).rglob("*.pdf")) if zotero_root and Path(zotero_root).exists() else []
    unpaywall_cache: Dict[str, Any] = {}
    return {
        "project": project or "",
        "backend": "SHawn-bio-search",
        "mode": "fast" if "fast mode" in " ".join(paper_block.get("warnings") or []) else "full",
        "run_label": datetime.now().strftime("%Y-%m-%d_%H%M%S_bio_search"),
        "query": paper_block.get("query") or bundle.get("query"),
        "effective_query": paper_block.get("effective_query"),
        "generated_at": datetime.now().astimezone().isoformat(),
        "results": [
            _normalize_result(p, i, pdf_files, unpaywall_email=unpaywall_email, unpaywall_cache=unpaywall_cache)
            for i, p in enumerate(papers, 1)
        ],
    }


def _build_datasets_results(bundle: Dict[str, Any], project: str = "", run_label: str = "") -> Dict[str, Any]:
    dataset_block = bundle.get("datasets") or {}
    datasets: List[Dict[str, Any]] = dataset_block.get("datasets") or []
    results = []
    for d in datasets:
        access_status = "open" if d.get("url") else "unknown"
        downloadable = bool(d.get("raw_available") or d.get("processed_available") or d.get("url"))
        results.append({
            "repository": d.get("repository"),
            "accession": d.get("accession"),
            "title": d.get("title"),
            "organism": d.get("organism"),
            "data_type": d.get("assay"),
            "summary": d.get("summary") or "",
            "url": d.get("url") or "",
            "download_url": d.get("url") or "",
            "access": {
                "status": access_status,
                "downloadable": downloadable,
                "check_method": "repository",
                "notes": "",
            },
            "retrieval_score": d.get("relevance_score"),
        })
    return {
        "project": project or "",
        "backend": "SHawn-bio-search",
        "run_label": run_label,
        "query": dataset_block.get("query") or bundle.get("query"),
        "generated_at": datetime.now().astimezone().isoformat(),
        "results": results,
    }


def _build_evidence_candidates(bundle: Dict[str, Any], search_results: Dict[str, Any], project: str = "") -> Dict[str, Any]:
    paper_block = bundle.get("papers") or {}
    papers: List[Dict[str, Any]] = paper_block.get("papers") or []
    claim_text = paper_block.get("effective_claim") or paper_block.get("claim") or ""
    by_key = {_citation_key(p, i): p for i, p in enumerate(papers, 1)}

    candidates = []
    for result in search_results.get("results", []):
        raw = by_key.get(result["citation_key"], {})
        candidates.append(
            {
                "bucket": raw.get("evidence_label") or "uncertain",
                "citation_key": result["citation_key"],
                "reason": raw.get("best_support_sentence") or raw.get("best_contradict_sentence") or "First-pass retrieval candidate",
                "directness": "direct" if (raw.get("evidence_label") in {"support", "contradict"}) else "indirect",
                "model_context": raw.get("source") or "unknown",
                "notes": f"evidence_score={raw.get('evidence_score', 0)}",
            }
        )

    return {
        "project": project or "",
        "backend": "SHawn-bio-search",
        "run_label": search_results.get("run_label"),
        "claims": [
            {
                "claim_id": "C001",
                "claim_text": claim_text,
                "candidates": candidates,
            }
        ] if claim_text else [],
    }


def _write_search_log(bundle: Dict[str, Any], out_path: Path) -> None:
    paper_block = bundle.get("papers") or {}
    dataset_block = bundle.get("datasets") or {}
    lines = [
        "# SEARCH_LOG",
        "",
        f"- search date: {datetime.now().astimezone().isoformat()}",
        f"- mode: {'fast' if 'fast mode' in ' '.join(paper_block.get('warnings') or []) else 'full'}",
        f"- original query: {paper_block.get('query') or bundle.get('query')}",
        f"- effective query: {paper_block.get('effective_query') or ''}",
        f"- project mode: {paper_block.get('project_mode') or ''}",
        f"- query expanded: {paper_block.get('query_expanded')}",
        f"- paper count: {len((paper_block.get('papers') or []))}",
        f"- dataset count: {len((dataset_block.get('datasets') or []))}",
        "",
        "## retrieval warnings",
    ]
    warnings = (paper_block.get("warnings") or []) + (dataset_block.get("warnings") or [])
    if warnings:
        lines.extend([f"- {w}" for w in warnings])
    else:
        lines.append("- none")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _write_availability_report(search_results: Dict[str, Any], datasets_results: Dict[str, Any], out_path: Path) -> None:
    papers = search_results.get("results") or []
    datasets = datasets_results.get("results") or []
    open_count = sum(1 for p in papers if ((p.get("access") or {}).get("status") == "open"))
    paywalled_count = sum(1 for p in papers if ((p.get("access") or {}).get("status") == "paywalled"))
    unknown_count = sum(1 for p in papers if ((p.get("access") or {}).get("status") == "unknown"))
    local_count = sum(1 for p in papers if ((p.get("local_library") or {}).get("found")))
    downloadable_count = sum(1 for p in papers if ((p.get("access") or {}).get("downloadable")))
    pdf_reachable_count = sum(1 for p in papers if ((p.get("access") or {}).get("pdf_reachable")))
    lines = [
        "# AVAILABILITY_REPORT",
        "",
        f"- generated_at: {datetime.now().astimezone().isoformat()}",
        f"- total paper candidates: {len(papers)}",
        f"- open access papers: {open_count}",
        f"- paywalled papers: {paywalled_count}",
        f"- unknown access papers: {unknown_count}",
        f"- downloadable papers: {downloadable_count}",
        f"- pdf reachable papers: {pdf_reachable_count}",
        f"- papers found in local library: {local_count}",
        f"- dataset candidates: {len(datasets)}",
        "",
        "## papers needing manual fetch",
    ]
    manual = [p for p in papers if not ((p.get("access") or {}).get("downloadable")) and not ((p.get("local_library") or {}).get("found"))]
    if manual:
        for p in manual[:50]:
            lines.append(f"- {p.get('title') or '(no title)'} | DOI: {p.get('doi') or ''} | URL: {p.get('url') or ''}")
    else:
        lines.append("- none")
    lines += ["", "## dataset repositories"]
    repo_counts: Dict[str, int] = {}
    for d in datasets:
        repo = d.get("repository") or "unknown"
        repo_counts[repo] = repo_counts.get(repo, 0) + 1
    if repo_counts:
        for repo, count in sorted(repo_counts.items()):
            lines.append(f"- {repo}: {count}")
    else:
        lines.append("- none")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _write_local_library_matches_csv(search_results: Dict[str, Any], out_path: Path) -> None:
    rows = []
    for p in search_results.get("results") or []:
        local = p.get("local_library") or {}
        access = p.get("access") or {}
        rows.append({
            "title": p.get("title") or "",
            "doi": p.get("doi") or "",
            "pmid": p.get("pmid") or "",
            "access_status": access.get("status") or "",
            "downloadable": str(bool(access.get("downloadable"))).lower(),
            "pdf_reachable": str(bool(access.get("pdf_reachable"))).lower(),
            "in_local_library": str(bool(local.get("found"))).lower(),
            "match_type": local.get("match_type") or "",
            "local_pdf_path": local.get("local_pdf_path") or "",
            "pdf_url": access.get("pdf_url") or "",
        })
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "title", "doi", "pmid", "access_status", "downloadable", "pdf_reachable",
            "in_local_library", "match_type", "local_pdf_path", "pdf_url"
        ])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export dual-engine handoff artifacts from bundle JSON")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--zotero-root", default="")
    parser.add_argument("--unpaywall-email", default=os.getenv("UNPAYWALL_EMAIL", ""))
    parser.add_argument("--legacy-evidence", action="store_true", help="Also export legacy EVIDENCE_CANDIDATES.json")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    search_results = _build_search_results(
        bundle,
        project=args.project,
        zotero_root=args.zotero_root,
        unpaywall_email=args.unpaywall_email,
    )
    datasets_results = _build_datasets_results(bundle, project=args.project, run_label=search_results.get("run_label") or "")

    (out_dir / "SEARCH_RESULTS.json").write_text(json.dumps(search_results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "DATASETS.json").write_text(json.dumps(datasets_results, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_search_log(bundle, out_dir / "SEARCH_LOG.md")
    _write_availability_report(search_results, datasets_results, out_dir / "AVAILABILITY_REPORT.md")
    _write_local_library_matches_csv(search_results, out_dir / "LOCAL_LIBRARY_MATCHES.csv")

    print(f"saved: {out_dir / 'SEARCH_RESULTS.json'}")
    print(f"saved: {out_dir / 'DATASETS.json'}")
    print(f"saved: {out_dir / 'SEARCH_LOG.md'}")
    print(f"saved: {out_dir / 'AVAILABILITY_REPORT.md'}")
    print(f"saved: {out_dir / 'LOCAL_LIBRARY_MATCHES.csv'}")

    if args.legacy_evidence:
        evidence_candidates = _build_evidence_candidates(bundle, search_results, project=args.project)
        (out_dir / "EVIDENCE_CANDIDATES.json").write_text(json.dumps(evidence_candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved: {out_dir / 'EVIDENCE_CANDIDATES.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
