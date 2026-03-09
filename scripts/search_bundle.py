#!/usr/bin/env python3
"""Run paper search and dataset search together in one command."""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

import dataset_search as ds
import gather_papers as gp


def _pick_sources(args: argparse.Namespace) -> List[Tuple[str, bool, Any]]:
    """Return paper source call order depending on fast-mode config."""
    if args.fast:
        # Fast mode: prioritize high-signal biomedical sources and avoid costly keys.
        return [
            ("pubmed", args.no_pubmed, gp.fetch_pubmed),
            ("europe_pmc", args.no_europepmc, gp.fetch_europe_pmc),
            ("openalex", args.no_openalex, gp.fetch_openalex),
        ]

    return [
        ("pubmed", args.no_pubmed, gp.fetch_pubmed),
        ("scopus", args.no_scopus, gp.fetch_scopus),
        ("google_scholar", args.no_scholar, gp.fetch_scholar_serpapi),
        ("europe_pmc", args.no_europepmc, gp.fetch_europe_pmc),
        ("openalex", args.no_openalex, gp.fetch_openalex),
        ("crossref", args.no_crossref, gp.fetch_crossref),
    ]


def run_papers(args: argparse.Namespace) -> Dict[str, Any]:
    papers: List[Dict[str, Any]] = []
    warnings: List[str] = []

    source_calls = _pick_sources(args)

    for name, skip, fn in source_calls:
        if skip:
            continue
        try:
            got = fn(args.query, args.max_papers_per_source)
            if name == "scopus" and not got and not os.getenv("SCOPUS_API_KEY"):
                warnings.append("scopus skipped: SCOPUS_API_KEY not set")
            if name == "google_scholar" and not got and not os.getenv("SERPAPI_API_KEY"):
                warnings.append("google_scholar skipped: SERPAPI_API_KEY not set")
            papers.extend(got)
        except Exception as exc:
            warnings.append(f"{name} failed: {exc}")

    papers = gp.dedupe_by_title_doi(papers)
    scored = [gp._score(p, args.claim, args.hypothesis) for p in papers]
    scored.sort(key=lambda x: x.get("evidence_score", 0), reverse=True)

    if args.fast:
        warnings.append("fast mode: focused on pubmed/europe_pmc/openalex only")

    return {
        "query": args.query,
        "claim": args.claim,
        "hypothesis": args.hypothesis,
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

    parser.add_argument("--out", default="")
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
