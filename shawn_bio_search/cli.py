"""Command-line interface for Shawn-Bio-Search."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

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
  HIGH      score >= 0.55 AND _rank_gap >= 0.15   top-1 candidate, dominant
  MEDIUM    score >= 0.40                         likely correct, review recommended
  LOW       score >= 0.25                         uncertain match
  UNLIKELY  score <  0.25                         wrong paper (different field/species)

  Note: only the top-1 candidate can earn HIGH; non-top candidates fall back
  to score-only thresholds. `_rank_gap` is the score separation between the
  top candidate and the runner-up (1.0 if there is only a single candidate).
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
    parser.add_argument("--project-mode", default="",
                        help="Apply a project-aware preset (e.g. endometrial-organoid-review, regenerative-screening)")
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
            results = search_papers(
                query=args.query,
                claim=args.claim,
                hypothesis=args.hypothesis,
                max_results=args.max_results,
                sources=sources,
                expand=args.expand_query,
                project_mode=args.project_mode,
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
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
