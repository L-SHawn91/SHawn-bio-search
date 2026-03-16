"""Command-line interface for Shawn-Bio-Search."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shawn_bio_search.search import search_papers


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
        """
    )
    
    parser.add_argument("-q", "--query", required=True, help="Search query")
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
