#!/usr/bin/env python3
"""Self-learning scoring calibration for SHawn-bio-search.

Implements three feedback loops:
  1. query_log  — records search quality (avg evidence, topic_guard hits)
  2. confidence_update — propagates manual dataset review back to YAML files
  3. guard_tune  — extends _TOPIC_GUARD_GROUPS from accumulated false positives

Usage:
  # Log a search run (call after every shawn-bio-search invocation)
  python3 scripts/self_learn_scoring.py log \\
      --query "endometrial cancer UCEC" --sources pubmed,openalex \\
      --n-results 15 --n-topguard-removed 3 --avg-evidence 0.52

  # Review accumulated log and suggest threshold updates
  python3 scripts/self_learn_scoring.py review

  # Apply confidence update from manual review file (TSV: accession \\t new_conf)
  python3 scripts/self_learn_scoring.py update-confidence \\
      --review-tsv /tmp/reviewed_datasets.tsv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIOINFO_ROOT = REPO_ROOT.parent / "SHawn-bioinfo"
REGISTRY_DIR = BIOINFO_ROOT / "registry" / "datasets"
QUERY_LOG = REPO_ROOT / "outputs" / "search_quality_log.tsv"
GUARD_LOG = REPO_ROOT / "outputs" / "topic_guard_false_positives.tsv"

QUERY_LOG.parent.mkdir(parents=True, exist_ok=True)


# ── Feedback loop 1: query quality logging ──────────────────────────────────

def cmd_log(args: argparse.Namespace) -> int:
    """Append one search run to the query quality log."""
    row = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "query": args.query,
        "sources": args.sources,
        "n_results": args.n_results,
        "n_topguard_removed": args.n_topguard_removed,
        "avg_evidence": args.avg_evidence,
        "min_evidence_used": args.min_evidence,
        "topic_guard_on": str(args.topic_guard_on),
    }
    write_header = not QUERY_LOG.exists()
    with open(QUERY_LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()), delimiter="\t")
        if write_header:
            w.writeheader()
        w.writerow(row)
    print(f"Logged search run to {QUERY_LOG}")
    return 0


# ── Feedback loop 2: review summary ─────────────────────────────────────────

def cmd_review(args: argparse.Namespace) -> int:
    """Analyse accumulated log and print calibration recommendations."""
    if not QUERY_LOG.exists():
        print("No query log found. Run some searches first.")
        return 0

    with open(QUERY_LOG, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    if not rows:
        print("Log is empty.")
        return 0

    runs = len(rows)
    avg_ev = sum(float(r["avg_evidence"]) for r in rows) / runs
    total_guard = sum(int(r["n_topguard_removed"]) for r in rows)
    total_results = sum(int(r["n_results"]) for r in rows)
    guard_rate = total_guard / max(total_results, 1)

    print(f"\n=== Search Quality Summary ({runs} runs) ===")
    print(f"  Average evidence score : {avg_ev:.3f}")
    print(f"  Topic guard removal    : {total_guard}/{total_results} ({guard_rate:.1%})")
    print()

    if avg_ev < 0.30:
        print("⚠ avg evidence < 0.30 — consider adding --min-evidence 0.25 to suppress noise")
    if avg_ev >= 0.45:
        print("✓ avg evidence ≥ 0.45 — search quality is good")
    if guard_rate > 0.20:
        print("⚠ >20% off-topic removal — consider domain-specific query refinement")
        print("  Tip: add tissue/species terms to narrow the query")

    print("\n=== Calibration Recommendations ===")
    if avg_ev < 0.35:
        print(f"  RECOMMENDED min_evidence threshold: 0.30 (current avg {avg_ev:.2f})")
    elif avg_ev < 0.45:
        print(f"  RECOMMENDED min_evidence threshold: 0.25 (current avg {avg_ev:.2f})")
    else:
        print(f"  min_evidence = 0.20 is sufficient (avg {avg_ev:.2f})")

    return 0


# ── Feedback loop 3: manual confidence update ────────────────────────────────

def cmd_update_confidence(args: argparse.Namespace) -> int:
    """Update linked_papers[].confidence in dataset YAMLs from a review TSV.

    TSV format: accession \\t doi_or_index \\t new_confidence \\t note
    """
    import yaml

    if not args.review_tsv:
        print("ERROR: --review-tsv required")
        return 1

    tsv_path = Path(args.review_tsv)
    if not tsv_path.exists():
        print(f"ERROR: {tsv_path} not found")
        return 1

    with open(tsv_path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t",
                                fieldnames=["accession", "doi", "new_conf", "note"])
        updates = list(reader)

    updated = 0
    for upd in updates:
        acc = upd["accession"].strip()
        doi = upd["doi"].strip()
        try:
            new_conf = float(upd["new_conf"])
        except (ValueError, TypeError):
            print(f"  SKIP bad confidence: {upd}")
            continue

        yaml_path = REGISTRY_DIR / f"{acc}.yaml"
        if not yaml_path.exists():
            # Try dot-escaped version
            escaped = acc.replace("/", "_").replace(":", "_")
            yaml_path = REGISTRY_DIR / f"{escaped}.yaml"
        if not yaml_path.exists():
            print(f"  SKIP missing YAML: {acc}")
            continue

        doc = yaml.safe_load(yaml_path.read_text()) or {}
        lp = doc.get("linked_papers") or []
        changed = False
        for paper in lp:
            if paper.get("doi", "").strip() == doi or doi == "*":
                paper["confidence"] = new_conf
                paper["extraction_method"] = "manual_review"
                changed = True
        if changed:
            # Re-write only linked_papers section
            lines = yaml_path.read_text().splitlines(keepends=True)
            # Simple approach: strip old linked_papers and rewrite
            doc["linked_papers"] = lp
            yaml_path.write_text(yaml.dump(doc, allow_unicode=True, default_flow_style=False))
            updated += 1
            print(f"  UPDATED {acc}: {doi} → conf={new_conf}")

    print(f"\nUpdated {updated}/{len(updates)} dataset files")
    return 0


# ── Feedback loop 4: guard term suggestion ──────────────────────────────────

def cmd_suggest_guard(args: argparse.Namespace) -> int:
    """Read false-positive log and suggest new topic_guard terms."""
    if not GUARD_LOG.exists():
        print("No false-positive log found.")
        return 0

    from collections import Counter
    with open(GUARD_LOG, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    term_counts: Counter = Counter()
    for r in rows:
        for tok in r.get("unguarded_tokens", "").split():
            if len(tok) >= 5:
                term_counts[tok] += 1

    print("=== Suggested new topic_guard terms (by frequency) ===")
    for term, cnt in term_counts.most_common(20):
        print(f"  {term:30s} {cnt} occurrences")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SHawn self-learning scoring calibration")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_log = sub.add_parser("log", help="Append a search run to the quality log")
    p_log.add_argument("--query", required=True)
    p_log.add_argument("--sources", default="pubmed,openalex")
    p_log.add_argument("--n-results", type=int, default=0)
    p_log.add_argument("--n-topguard-removed", type=int, default=0)
    p_log.add_argument("--avg-evidence", type=float, default=0.0)
    p_log.add_argument("--min-evidence", type=float, default=0.0)
    p_log.add_argument("--topic-guard-on", action="store_true")

    sub.add_parser("review", help="Analyse quality log and recommend thresholds")

    p_upd = sub.add_parser("update-confidence", help="Propagate manual review to YAML files")
    p_upd.add_argument("--review-tsv", required=True)

    sub.add_parser("suggest-guard", help="Suggest new topic_guard terms from false-positive log")

    args = ap.parse_args(argv)
    dispatch = {"log": cmd_log, "review": cmd_review,
                "update-confidence": cmd_update_confidence,
                "suggest-guard": cmd_suggest_guard}
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
