#!/usr/bin/env python3
"""Run paper search and dataset search together in one command."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _load_openclaw_shared_env import load_openclaw_shared_env
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

import dataset_search as ds
import gather_papers as gp
from shawn_bio_search.presets import apply_project_preset
from shawn_bio_search.query_expansion import expand_query
from shawn_bio_search.scoring import classify_evidence_label
from shawn_bio_search.llm_triage import triage_papers
from export_dual_engine_bundle import (
    _build_datasets_results,
    _build_evidence_candidates,
    _build_search_results,
    _write_availability_report,
    _write_local_library_matches_csv,
    _write_search_log,
)

load_openclaw_shared_env()


def _pick_sources(args: argparse.Namespace) -> List[Tuple[str, bool, Any]]:
    """Return paper source call order depending on fast-mode config."""
    if args.fast:
        # Fast mode: prioritize high-signal biomedical sources and avoid costly keys.
        return [
            ("pubmed", args.no_pubmed, gp.fetch_pubmed),
            ("semantic_scholar", args.no_semantic_scholar, gp.fetch_semanticscholar),
            ("europe_pmc", args.no_europepmc, gp.fetch_europe_pmc),
            ("openalex", args.no_openalex, gp.fetch_openalex),
        ]

    return [
        ("pubmed", args.no_pubmed, gp.fetch_pubmed),
        ("semantic_scholar", args.no_semantic_scholar, gp.fetch_semanticscholar),
        ("scopus", args.no_scopus, gp.fetch_scopus),
        ("google_scholar", args.no_scholar, gp.fetch_scholar_serpapi),
        ("europe_pmc", args.no_europepmc, gp.fetch_europe_pmc),
        ("openalex", args.no_openalex, gp.fetch_openalex),
        ("crossref", args.no_crossref, gp.fetch_crossref),
    ]


def run_papers(args: argparse.Namespace) -> Dict[str, Any]:
    papers: List[Dict[str, Any]] = []
    warnings: List[str] = []

    preset_info = apply_project_preset(query=args.query, claim=args.claim, project_mode=args.project_mode)
    effective_query = preset_info["effective_query"]
    effective_claim = preset_info["effective_claim"]
    if args.expand_query:
        effective_query = expand_query(effective_query)

    source_calls = _pick_sources(args)

    for name, skip, fn in source_calls:
        if skip:
            continue
        try:
            got = fn(effective_query, args.max_papers_per_source)
            if name == "semantic_scholar" and not got and not (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY")):
                warnings.append("semantic_scholar skipped: API key not set")
            if name == "scopus" and not got and not os.getenv("SCOPUS_API_KEY"):
                warnings.append("scopus skipped: SCOPUS_API_KEY not set")
            if name == "google_scholar" and not got and not os.getenv("SERPAPI_API_KEY"):
                warnings.append("google_scholar skipped: SERPAPI_API_KEY not set")
            papers.extend(got)
        except Exception as exc:
            warnings.append(f"{name} failed: {exc}")

    papers = gp.dedupe_by_title_doi(papers)
    scored = [gp._score(p, effective_claim, args.hypothesis) for p in papers]
    for p in scored:
        p["evidence_label"] = classify_evidence_label(
            support_score=float(p.get("support_score") or 0.0),
            contradiction_score=float(p.get("contradiction_score") or 0.0),
            evidence_score=float(p.get("evidence_score") or 0.0),
            has_claim=bool((effective_claim or "").strip()),
        )
    scored.sort(key=lambda x: x.get("evidence_score", 0), reverse=True)
    scored, llm_triage_meta = triage_papers(
        scored,
        query=effective_query,
        claim=effective_claim,
        hypothesis=args.hypothesis,
        enabled=args.llm_triage,
        model=args.llm_model,
        fallback_chain=args.llm_fallback_chain,
        limit=args.llm_limit,
        timeout=args.llm_timeout,
        rerank=args.llm_rerank,
    )

    if args.fast:
        warnings.append("fast mode: focused on pubmed/europe_pmc/openalex only")

    return {
        "query": args.query,
        "effective_query": effective_query,
        "claim": args.claim,
        "effective_claim": effective_claim,
        "hypothesis": args.hypothesis,
        "project_mode": args.project_mode,
        "query_expanded": bool(args.expand_query),
        "llm_triage": llm_triage_meta,
        "count": len(scored),
        "warnings": warnings,
        "papers": scored,
    }


def run_datasets(args: argparse.Namespace) -> Dict[str, Any]:
    if args.fast and not args.include_datasets:
        return {
            "query": args.query,
            "organism": args.organism,
            "assay": args.assay,
            "count": 0,
            "warnings": ["dataset search skipped in fast mode (set --include-datasets to force)"],
            "datasets": [],
        }

    datasets: List[Dict[str, Any]] = []
    warnings: List[str] = []

    source_calls = [
        ("geo", args.no_geo, ds.fetch_geo),
        ("sra", args.no_sra, ds.fetch_sra),
        ("bioproject", args.no_bioproject, ds.fetch_bioproject),
        ("arrayexpress", args.no_arrayexpress, ds.fetch_arrayexpress),
        ("pride", args.no_pride, ds.fetch_pride),
        ("ena", args.no_ena, ds.fetch_ena),
        ("bigd", args.no_bigd, ds.fetch_bigd),
        ("cngb", args.no_cngb, ds.fetch_cngb),
        ("ddbj", args.no_ddbj, ds.fetch_ddbj),
    ]

    for name, skip, fn in source_calls:
        if skip:
            continue
        try:
            datasets.extend(fn(args.query, args.max_datasets_per_source))
        except Exception as exc:
            warnings.append(f"{name} failed: {exc}")

    datasets = ds.dedupe(datasets)
    scored = [ds._score_dataset(d, args.query, args.organism, args.assay) for d in datasets]
    scored.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    return {
        "query": args.query,
        "organism": args.organism,
        "assay": args.assay,
        "count": len(scored),
        "warnings": warnings,
        "datasets": scored,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper + dataset unified search (global)")
    parser.add_argument("--query", required=True)
    parser.add_argument("--claim", default="")
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--organism", default="")
    parser.add_argument("--assay", default="")
    parser.add_argument("--max-papers-per-source", type=int, default=15)
    parser.add_argument("--max-datasets-per-source", type=int, default=15)

    parser.add_argument("--no-pubmed", action="store_true")
    parser.add_argument("--no-semantic-scholar", action="store_true")
    parser.add_argument("--no-scopus", action="store_true")
    parser.add_argument("--no-scholar", action="store_true")
    parser.add_argument("--no-europepmc", action="store_true")
    parser.add_argument("--no-openalex", action="store_true")
    parser.add_argument("--no-crossref", action="store_true")

    parser.add_argument("--no-geo", action="store_true")
    parser.add_argument("--no-sra", action="store_true")
    parser.add_argument("--no-bioproject", action="store_true")
    parser.add_argument("--no-arrayexpress", action="store_true")
    parser.add_argument("--no-pride", action="store_true")
    parser.add_argument("--no-ena", action="store_true")
    parser.add_argument("--no-bigd", action="store_true")
    parser.add_argument("--no-cngb", action="store_true")
    parser.add_argument("--no-ddbj", action="store_true")

    parser.add_argument("--fast", action="store_true", help="Fast run: paper-focused, skip Scopus/Scholar/Crossref + dataset by default")
    parser.add_argument("--include-datasets", action="store_true", help="Run dataset search even in fast mode")
    parser.add_argument("--expand-query", action="store_true", help="Expand query with lightweight biomedical synonyms")
    parser.add_argument("--project-mode", default="", help="Apply a project-aware preset")
    parser.add_argument("--llm-triage", action="store_true", help="Enrich top paper candidates with Ollama semantic triage")
    parser.add_argument("--llm-model", default="", help="Preferred Ollama model for --llm-triage")
    parser.add_argument("--llm-fallback-chain", default="", help="Comma-separated Ollama/code fallback chain for --llm-triage")
    parser.add_argument("--llm-limit", type=int, default=12, help="Number of top paper candidates to triage")
    parser.add_argument("--llm-timeout", type=float, default=30.0, help="Per-model Ollama timeout in seconds")
    parser.add_argument("--llm-rerank", action="store_true", help="Rerank triaged candidates by evidence score + LLM relevance")

    parser.add_argument("--out", default="")
    parser.add_argument("--export-dual-engine-dir", default="", help="Optional output dir for SEARCH_RESULTS.json / DATASETS.json / SEARCH_LOG.md and sidecars")
    parser.add_argument("--project", default="", help="Optional project label for dual-engine export")
    parser.add_argument("--zotero-root", default="", help="Optional Zotero/local paper root for local library matching")
    parser.add_argument("--unpaywall-email", default=os.getenv("UNPAYWALL_EMAIL", ""), help="Optional Unpaywall email for OA/access enrichment")
    parser.add_argument("--legacy-evidence", action="store_true", help="Also export legacy EVIDENCE_CANDIDATES.json for compatibility")
    args = parser.parse_args()

    if args.fast:
        args.max_papers_per_source = min(args.max_papers_per_source or 8, 8)
        args.max_datasets_per_source = min(args.max_datasets_per_source or 5, 5)

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_map = {
            ex.submit(run_papers, args): "papers",
            ex.submit(run_datasets, args): "datasets",
        }
        for fut in as_completed(fut_map):
            results[fut_map[fut]] = fut.result()

    bundle = {"query": args.query, "papers": results.get("papers", {}), "datasets": results.get("datasets", {})}

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=2)
        print(f"saved: {args.out}")
    else:
        print(json.dumps(bundle, ensure_ascii=False, indent=2))

    if args.export_dual_engine_dir:
        out_dir = Path(args.export_dual_engine_dir)
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
