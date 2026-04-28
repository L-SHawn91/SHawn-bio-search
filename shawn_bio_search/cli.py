"""Command-line interface for Shawn-Bio-Search."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shawn_bio_search.search import search_papers, search_authors


def main(argv: Optional[list] = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Shawn-Bio-Search: Multi-source biomedical literature search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -q "organoid stem cell" -c "ECM is essential"
  %(prog)s -q "cancer immunotherapy" --max 20 -f markdown
  %(prog)s -q "COVID-19" --sources pubmed,europe_pmc
  %(prog)s -q "endometrial organoid" --project-mode endometrial-organoid-review --expand-query -f json
  %(prog)s --mode author -q "Hakhyun Ka" --author-aliases "Ka H,H. Ka" --affiliation "Yonsei"

Citation verification confidence levels (verify_citation API):
  HIGH      score >= 0.60   correct paper with high certainty
  MEDIUM    score >= 0.35   likely correct, manual check recommended
  LOW       score >= 0.15   uncertain match
  MISMATCH  score <  0.15   wrong paper (different field/species)
        """
    )
    
    parser.add_argument("-q", "--query", required=True, help="Search query")
    parser.add_argument("--mode", choices=["broad", "author"], default="broad",
                        help="Search mode: broad literature search or author-centric retrieval")
    parser.add_argument("--author-aliases", default="",
                        help="Comma-separated author aliases for author mode")
    parser.add_argument("--affiliation", default="",
                        help="Affiliation hint for author mode (e.g. Yonsei University)")
    parser.add_argument("--publication-limit", type=int, default=25,
                        help="Max publications to fetch per author in author mode")
    parser.add_argument("--no-scival", action="store_true",
                        help="Disable SciVal metric enrichment in author mode")
    parser.add_argument("-c", "--claim", default="", help="Claim to verify (optional)")
    parser.add_argument("--hypothesis", default="", help="Hypothesis to test (optional)")
    parser.add_argument("-n", "--max", type=int, default=10, dest="max_results",
                        help="Max results per source (default: 10)")
    parser.add_argument("-s", "--sources", default="",
                        help="Comma-separated sources (default: all)")
    parser.add_argument("--expand-query", action="store_true",
                        help="Expand query with lightweight biomedical synonyms")
    parser.add_argument(
        "--no-expand-safe",
        action="store_true",
        help=(
            "Disable safe-mode query expansion.  By default expansion only appends "
            "synonyms when the query contains a recognized biomedical domain token, "
            "preventing cross-domain drift.  Use this flag to restore unconstrained "
            "expansion behaviour."
        ),
    )
    parser.add_argument("--project-mode", default="",
                        help="Apply a project-aware preset (e.g. endometrial-organoid-review, regenerative-screening)")
    parser.add_argument("--llm-triage", action="store_true",
                        help="Enrich top paper candidates with Ollama semantic triage")
    parser.add_argument("--llm-model", default="",
                        help="Preferred Ollama model for --llm-triage")
    parser.add_argument("--llm-fallback-chain", default="",
                        help="Comma-separated Ollama/code fallback chain for --llm-triage")
    parser.add_argument("--llm-limit", type=int, default=12,
                        help="Number of top candidates to triage with --llm-triage")
    parser.add_argument("--llm-timeout", type=float, default=30.0,
                        help="Per-model Ollama timeout in seconds for --llm-triage")
    parser.add_argument("--llm-rerank", action="store_true",
                        help="Rerank triaged candidates by evidence score + LLM relevance")
    parser.add_argument(
        "--min-evidence",
        type=float,
        default=0.0,
        metavar="THRESHOLD",
        help=(
            "Minimum evidence_score to include in results (default: 0.0 = no filter). "
            "Recommended: 0.25 to suppress low-quality false positives."
        ),
    )
    _tg = parser.add_mutually_exclusive_group()
    _tg.add_argument(
        "--topic-guard",
        dest="topic_guard",
        action="store_true",
        default=None,
        help=(
            "Remove papers mentioning off-topic organisms/tissues (plant, prostate, "
            "cervical, hepatic, renal) unless those terms appear in the query.  "
            "Auto-enabled when --expand-query is used."
        ),
    )
    _tg.add_argument(
        "--no-topic-guard",
        dest="topic_guard",
        action="store_false",
        help="Explicitly disable topic guard, overriding the auto-enable that occurs with --expand-query.",
    )
    parser.add_argument("-f", "--format", choices=["json", "plain", "markdown"],
                        default="plain", help="Output format (default: plain)")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    
    args = parser.parse_args(argv)
    
    # Parse sources
    sources = None
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    
    # Search
    try:
        if args.mode == "author":
            aliases = [s.strip() for s in args.author_aliases.split(",") if s.strip()]
            results = search_authors(
                query=args.query,
                author_aliases=aliases,
                affiliation=args.affiliation,
                max_results=args.max_results,
                publication_limit=args.publication_limit,
                include_scival=not args.no_scival,
            )
        else:
            # topic_guard: None means "let search_papers decide" (auto-enable
            # when expand is active).  True/False are explicit overrides.
            from shawn_bio_search.search import _SENTINEL as _TG_SENTINEL  # noqa: PLC0415
            tg_value = args.topic_guard  # None | True | False
            results = search_papers(
                query=args.query,
                claim=args.claim,
                hypothesis=args.hypothesis,
                max_results=args.max_results,
                sources=sources,
                expand=args.expand_query,
                expand_safe=not args.no_expand_safe,
                project_mode=args.project_mode,
                llm_triage=args.llm_triage,
                llm_model=args.llm_model,
                llm_fallback_chain=args.llm_fallback_chain,
                llm_limit=args.llm_limit,
                llm_timeout=args.llm_timeout,
                llm_rerank=args.llm_rerank,
                min_evidence=args.min_evidence,
                topic_guard=_TG_SENTINEL if tg_value is None else tg_value,
            )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    
    # Format output
    if args.format == "json":
        output = results.to_json()
    elif args.format == "markdown":
        output = results.to_markdown()
    else:  # plain
        output = results.to_plain()
    
    # Write output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Results written to: {args.output}")
    else:
        print(output)

    # Auto-log to self-learning quality tracker (best-effort, never fails the CLI)
    _auto_log_search(args, results)

    return 0


def _auto_log_search(args: "argparse.Namespace", results: Any) -> None:
    """Append this search run to the quality log for self-learning calibration."""
    try:
        from pathlib import Path as _Path
        import sys as _sys
        _scripts = _Path(__file__).resolve().parents[1] / "scripts"
        _sys.path.insert(0, str(_scripts.parent))
        from scripts.self_learn_scoring import cmd_log  # noqa: PLC0415
        import argparse as _ap  # noqa: PLC0415

        papers = getattr(results, "papers", None) or []
        n_results = len(papers)
        n_topguard = sum(1 for p in papers if p.get("topic_guard_filtered"))
        avg_ev = (
            sum(p.get("evidence_score", 0.0) for p in papers) / n_results
            if n_results else 0.0
        )
        sources_used = getattr(results, "sources_searched", None)
        sources_str = ",".join(sources_used) if sources_used else getattr(args, "sources", "")

        log_ns = _ap.Namespace(
            query=args.query,
            sources=sources_str,
            n_results=n_results,
            n_topguard_removed=n_topguard,
            avg_evidence=round(avg_ev, 4),
            min_evidence=getattr(args, "min_evidence", 0.0),
            topic_guard_on=bool(getattr(args, "topic_guard", False)),
        )
        cmd_log(log_ns)
    except Exception:
        pass  # logging is optional; never break the CLI


if __name__ == "__main__":
    sys.exit(main())
