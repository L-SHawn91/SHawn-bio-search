#!/usr/bin/env python3
"""Build a stronger review citation list from bundle search output."""

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def tokenize(s: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]{3,}", (s or "").lower()))


def kw_match(title: str, include: List[str], exclude: List[str]) -> bool:
    t = (title or "").lower()
    if include and not all(k in t for k in include):
        return False
    if exclude and any(k in t for k in exclude):
        return False
    return True


def classify_section(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ["long-term", "self-renewing", "development of organoids", "hormone-responsive"]):
        return "Foundational"
    if any(k in t for k in ["implant", "trophoblast", "receptiv", "placenta", "pregnan"]):
        return "Implantation & Interface"
    if any(k in t for k in ["protocol", "method", "hydrogel", "matrix", "co-culture", "bioprint", "model"]):
        return "Methods & Engineering"
    if any(k in t for k in ["disease", "cancer", "endometriosis", "therapy", "drug", "asherman"]):
        return "Disease & Translation"
    return "General"


def blended_score(p: Dict[str, Any]) -> float:
    ev = float(p.get("evidence_score") or 0)
    cites = int(p.get("citations") or 0)
    year = int(p.get("year") or 0)
    source_weight = float(p.get("source_weight") or 0.88)
    current = datetime.now().year
    recency = 0.0
    if 1900 <= year <= current:
        recency = max(0.0, 1.0 - ((current - year) / 20.0))
    cite_component = min(math.log10(cites + 1) / 3.0, 1.0)
    return round(0.55 * ev + 0.25 * cite_component + 0.10 * recency + 0.10 * source_weight, 4)


def format_citation(p: Dict[str, Any]) -> str:
    authors = p.get("authors") or []
    if isinstance(authors, list):
        author_str = ", ".join([str(a) for a in authors[:4]])
        if len(authors) > 4:
            author_str += ", et al."
    else:
        author_str = str(authors)
    title = p.get("title") or "Untitled"
    year = p.get("year") or "n.d."
    doi = p.get("doi")
    url = p.get("url") or ""
    source = p.get("source") or "unknown"
    cites = p.get("citations") or 0
    score = p.get("review_score")
    support_sentence = (p.get("best_support_sentence") or "").strip()
    contra_score = p.get("contradiction_score")
    support_tail = ""
    if support_sentence:
        support_tail = f' Evidence: "{support_sentence}"'
    if contra_score is not None:
        support_tail += f" ContraScore: {contra_score}."
    else:
        support_tail += "."

    if doi:
        return f"{author_str} ({year}). {title}. DOI: {doi}. Source: {source}. Cited-by: {cites}. Score: {score}.{support_tail}"
    return f"{author_str} ({year}). {title}. URL: {url}. Source: {source}. Cited-by: {cites}. Score: {score}.{support_tail}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build review-ready citation list from bundle JSON")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--source-cap", type=int, default=8)
    parser.add_argument("--min-year", type=int, default=0)
    parser.add_argument("--doi-only", action="store_true")
    parser.add_argument("--include", default="")
    parser.add_argument("--exclude", default="")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text())
    papers = (bundle.get("papers") or {}).get("papers") or []

    include = [x.strip().lower() for x in args.include.split(",") if x.strip()]
    exclude = [x.strip().lower() for x in args.exclude.split(",") if x.strip()]

    dedup: Dict[str, Dict[str, Any]] = {}
    for p in papers:
        title = p.get("title") or ""
        doi = (p.get("doi") or "").strip().lower()
        key = doi or title.strip().lower()
        if not key:
            continue
        if args.doi_only and not doi:
            continue
        year = int(p.get("year") or 0)
        if args.min_year and year and year < args.min_year:
            continue
        if not kw_match(title, include, exclude):
            continue

        p2 = dict(p)
        p2["review_score"] = blended_score(p2)

        prev = dedup.get(key)
        if prev is None or p2["review_score"] > prev.get("review_score", 0):
            dedup[key] = p2

    ranked = sorted(dedup.values(), key=lambda x: x.get("review_score", 0), reverse=True)

    selected = []
    per_source = defaultdict(int)
    for p in ranked:
        src = p.get("source") or "unknown"
        if per_source[src] >= args.source_cap:
            continue
        selected.append(p)
        per_source[src] += 1
        if len(selected) >= args.top:
            break

    sections = defaultdict(list)
    for p in selected:
        sections[classify_section(p.get("title") or "")].append(p)

    lines = []
    lines.append("# Review Citation List")
    lines.append("")
    lines.append(f"- Query: {bundle.get('query')}")
    lines.append(f"- Total candidates: {len(papers)}")
    lines.append(f"- Selected: {len(selected)}")
    lines.append(f"- DOI only: {args.doi_only}")
    lines.append("")

    order = ["Foundational", "Disease & Translation", "Implantation & Interface", "Methods & Engineering", "General"]
    n = 1
    for sec in order:
        if not sections.get(sec):
            continue
        lines.append(f"## {sec}")
        for p in sections[sec]:
            lines.append(f"{n}. {format_citation(p)}")
            n += 1
        lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"saved: {args.out}")
    print(f"selected: {len(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
