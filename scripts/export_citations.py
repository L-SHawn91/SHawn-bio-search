#!/usr/bin/env python3
"""Export citations from bundle JSON to BibTeX/CSV/Markdown list."""

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List


def normalize(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", (s or "").lower())


def first_author(authors: Any) -> str:
    if isinstance(authors, list) and authors:
        a = str(authors[0]).strip()
        if "," in a:
            return a.split(",")[0].strip()
        if " " in a:
            return a.split(" ")[-1].strip()
        return a
    return "anon"


def bib_key(p: Dict[str, Any], idx: int) -> str:
    y = str(p.get("year") or "nd")
    a = normalize(first_author(p.get("authors")))[:12] or "anon"
    t = normalize((p.get("title") or "")[:30])[:16] or f"paper{idx}"
    return f"{a}{y}{t}"


def dedupe(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for p in papers:
        k = ((p.get("doi") or "").lower(), (p.get("title") or "").strip().lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def export_bibtex(papers: List[Dict[str, Any]], out_path: Path) -> None:
    lines: List[str] = []
    for i, p in enumerate(papers, 1):
        key = bib_key(p, i)
        authors = p.get("authors") or []
        author_field = " and ".join([str(a) for a in authors]) if isinstance(authors, list) else str(authors)
        title = (p.get("title") or "").replace("{", "\\{").replace("}", "\\}")
        venue = (p.get("venue") or "")
        year = p.get("year") or ""
        doi = p.get("doi") or ""
        url = p.get("url") or ""
        abstract = (p.get("abstract") or "").replace("{", "\\{").replace("}", "\\}")

        lines.append(f"@article{{{key},")
        if author_field:
            lines.append(f"  author = {{{author_field}}},")
        if title:
            lines.append(f"  title = {{{title}}},")
        if venue:
            lines.append(f"  journal = {{{venue}}},")
        if year:
            lines.append(f"  year = {{{year}}},")
        if doi:
            lines.append(f"  doi = {{{doi}}},")
        if url:
            lines.append(f"  url = {{{url}}},")
        if abstract:
            lines.append(f"  abstract = {{{abstract}}},")
        lines.append("}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def export_csv(papers: List[Dict[str, Any]], out_path: Path) -> None:
    fields = [
        "source",
        "title",
        "authors",
        "year",
        "doi",
        "url",
        "citations",
        "evidence_score",
        "claim_overlap",
        "hypothesis_overlap",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in papers:
            authors = p.get("authors") or []
            author_str = "; ".join([str(a) for a in authors]) if isinstance(authors, list) else str(authors)
            w.writerow(
                {
                    "source": p.get("source"),
                    "title": p.get("title"),
                    "authors": author_str,
                    "year": p.get("year"),
                    "doi": p.get("doi"),
                    "url": p.get("url"),
                    "citations": p.get("citations"),
                    "evidence_score": p.get("evidence_score"),
                    "claim_overlap": p.get("claim_overlap"),
                    "hypothesis_overlap": p.get("hypothesis_overlap"),
                }
            )


def export_markdown(papers: List[Dict[str, Any]], out_path: Path) -> None:
    lines = ["# Citation List", ""]
    for i, p in enumerate(papers, 1):
        authors = p.get("authors") or []
        author_str = ", ".join([str(a) for a in authors[:6]]) if isinstance(authors, list) else str(authors)
        if isinstance(authors, list) and len(authors) > 6:
            author_str += ", et al."
        doi = p.get("doi")
        ref = f"DOI: {doi}" if doi else f"URL: {p.get('url') or ''}"
        lines.append(f"{i}. {author_str} ({p.get('year') or 'n.d.'}). {p.get('title')}. {ref}")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export citations from bundle JSON")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--doi-only", action="store_true")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text())
    papers = (bundle.get("papers") or {}).get("papers") or []
    papers = dedupe(papers)

    if args.doi_only:
        papers = [p for p in papers if p.get("doi")]

    papers = sorted(papers, key=lambda p: float(p.get("evidence_score") or 0), reverse=True)[: args.top]

    prefix = Path(args.out_prefix)
    export_bibtex(papers, Path(str(prefix) + ".bib"))
    export_csv(papers, Path(str(prefix) + ".csv"))
    export_markdown(papers, Path(str(prefix) + ".md"))

    print(f"exported_bib: {str(prefix)}.bib")
    print(f"exported_csv: {str(prefix)}.csv")
    print(f"exported_md: {str(prefix)}.md")
    print(f"count: {len(papers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
