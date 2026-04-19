#!/usr/bin/env python3
"""Precision/recall benchmark for shawn_bio_search.sources.pubmed.verify_citation.

Runs verify_citation() on a curated set of gold citations (optionally including
adversarial same-author-same-year decoys) and reports:

  * top1_precision  — fraction of queries where the top-ranked result matches
                      the expected PMID/DOI (the core metric this benchmark
                      was designed for — replaces the recall-only claim that
                      "10/10 scored HIGH").
  * recall@3, @10   — fraction where the intended paper appears in top-3 / 10.
  * HIGH_precision  — of queries whose top-1 was flagged HIGH, fraction whose
                      top-1 is actually correct. This is the number you want
                      to be high when trusting HIGH labels downstream.
  * confusion table — rows = expected confidence outcome, cols = actual.

Usage (from repo root, on a machine with NCBI/Crossref access):

    python3 scripts/bench_verify_citation.py \
        --seed tests/data/citation_benchmark_seed.json \
        --out outputs/bench_verify_citation.json

Network required. Honors NCBI_API_KEY / CROSSREF_EMAIL / S2_API_KEY envs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------ #
# Matching helpers
# ------------------------------------------------------------------ #

def _norm_doi(x: Optional[str]) -> str:
    if not x:
        return ""
    return x.strip().lower().removeprefix("https://doi.org/")


def _match(result: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    """A result counts as the expected paper if PMID or DOI matches."""
    exp_pmid = (expected.get("expected_pmid") or "").strip()
    exp_doi = _norm_doi(expected.get("expected_doi"))
    got_pmid = (result.get("pmid") or "").strip()
    got_doi = _norm_doi(result.get("doi"))
    if exp_pmid and exp_pmid != "TBD" and got_pmid == exp_pmid:
        return True
    if exp_doi and exp_doi != "tbd" and got_doi == exp_doi:
        return True
    return False


# ------------------------------------------------------------------ #
# Benchmark loop
# ------------------------------------------------------------------ #

def run_one(case: Dict[str, Any], sleep: float = 0.4) -> Dict[str, Any]:
    """Run verify_citation on a single case, record top-3 snapshot + metrics."""
    # Import lazily so --help works without the package installed
    from shawn_bio_search.sources.pubmed import verify_citation

    t0 = time.time()
    results = verify_citation(
        first_author=case["first_author"],
        year=case["year"],
        context_keywords=case.get("context_keywords"),
        context_sentence=case.get("context_sentence"),
        use_crossref=True,
        use_semanticscholar=True,
    )
    elapsed = time.time() - t0

    top3 = results[:3]
    top1_match = bool(top3) and _match(top3[0], case)
    recall_at_3 = any(_match(r, case) for r in top3)
    recall_at_10 = any(_match(r, case) for r in results[:10])

    snapshot = [
        {
            "pmid": r.get("pmid"),
            "doi": r.get("doi"),
            "title": (r.get("title") or "")[:90],
            "context_score": round(r.get("_context_score", 0.0), 3),
            "rank_gap": r.get("_rank_gap"),
            "confidence": r.get("_verification_confidence"),
            "strategy": r.get("_search_strategy"),
            "match": _match(r, case),
        }
        for r in top3
    ]

    time.sleep(sleep)
    return {
        "id": case.get("id"),
        "expected_pmid": case.get("expected_pmid"),
        "expected_doi": case.get("expected_doi"),
        "n_candidates": len(results),
        "elapsed_sec": round(elapsed, 2),
        "top1_match": top1_match,
        "recall_at_3": recall_at_3,
        "recall_at_10": recall_at_10,
        "top1_confidence": top3[0].get("_verification_confidence") if top3 else None,
        "top1_score": round(top3[0].get("_context_score", 0.0), 3) if top3 else None,
        "top1_gap": top3[0].get("_rank_gap") if top3 else None,
        "top3_snapshot": snapshot,
    }


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(records)
    if n == 0:
        return {"n": 0}
    top1 = sum(1 for r in records if r["top1_match"])
    r3 = sum(1 for r in records if r["recall_at_3"])
    r10 = sum(1 for r in records if r["recall_at_10"])

    # HIGH-precision: of those flagged HIGH, how many actually matched
    high = [r for r in records if r.get("top1_confidence") == "HIGH"]
    high_correct = sum(1 for r in high if r["top1_match"])

    # Confidence confusion (predicted conf vs ground-truth correct/wrong)
    conf_confusion: Dict[str, Dict[str, int]] = {}
    for r in records:
        c = r.get("top1_confidence") or "NONE"
        bucket = "correct" if r["top1_match"] else "wrong"
        conf_confusion.setdefault(c, {"correct": 0, "wrong": 0})[bucket] += 1

    return {
        "n": n,
        "top1_precision": round(top1 / n, 3),
        "recall_at_3":    round(r3 / n, 3),
        "recall_at_10":   round(r10 / n, 3),
        "high_count":     len(high),
        "high_precision": round(high_correct / len(high), 3) if high else None,
        "confidence_confusion": conf_confusion,
    }


def print_summary(summary: Dict[str, Any]) -> None:
    print()
    print("===== Benchmark Summary =====")
    print(f"n cases            : {summary['n']}")
    print(f"top1_precision     : {summary['top1_precision']}")
    print(f"recall@3           : {summary['recall_at_3']}")
    print(f"recall@10          : {summary['recall_at_10']}")
    print(f"HIGH count         : {summary['high_count']}")
    print(f"HIGH_precision     : {summary['high_precision']}")
    print()
    print("Confidence confusion (top-1 confidence × correctness):")
    print(f"  {'confidence':<10} {'correct':>7} {'wrong':>7}")
    for conf, counts in sorted(summary["confidence_confusion"].items()):
        print(f"  {conf:<10} {counts['correct']:>7} {counts['wrong']:>7}")


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=Path, required=True,
                    help="Path to citation_benchmark_seed.json")
    ap.add_argument("--out", type=Path, default=Path("outputs/bench_verify_citation.json"),
                    help="Where to write per-case + summary JSON")
    ap.add_argument("--include-adversarial", action="store_true",
                    help="Also run the 'adversarial' section of the seed file")
    ap.add_argument("--sleep", type=float, default=0.4,
                    help="Pause between cases to respect NCBI rate limits")
    args = ap.parse_args(argv)

    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    cases: List[Dict[str, Any]] = list(seed.get("gold", []))
    if args.include_adversarial:
        cases.extend(seed.get("adversarial", []))

    # Skip template entries that still have TBD expected_pmid AND no doi.
    resolved = []
    skipped = []
    for c in cases:
        pmid_ok = c.get("expected_pmid") and c.get("expected_pmid") != "TBD"
        doi_ok = c.get("expected_doi") and c.get("expected_doi") != "TBD"
        if pmid_ok or doi_ok:
            resolved.append(c)
        else:
            skipped.append(c.get("id"))

    if skipped:
        print(f"[warn] skipping {len(skipped)} case(s) with TBD ground truth: {skipped}",
              file=sys.stderr)

    if not resolved:
        print("[error] no resolved cases to run — fill in expected_pmid/expected_doi",
              file=sys.stderr)
        return 2

    records: List[Dict[str, Any]] = []
    for i, case in enumerate(resolved, 1):
        print(f"[{i}/{len(resolved)}] {case['id']} — {case['first_author']} {case['year']}",
              file=sys.stderr)
        try:
            records.append(run_one(case, sleep=args.sleep))
        except Exception as e:  # pragma: no cover — live-network failures
            print(f"  error: {type(e).__name__}: {e}", file=sys.stderr)
            records.append({"id": case["id"], "error": str(e), "top1_match": False,
                            "recall_at_3": False, "recall_at_10": False,
                            "top1_confidence": "ERROR"})

    summary = summarize([r for r in records if "error" not in r])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"summary": summary, "records": records}, indent=2),
        encoding="utf-8",
    )
    print(f"[ok] wrote {args.out}", file=sys.stderr)
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
