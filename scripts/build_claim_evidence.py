#!/usr/bin/env python3
"""Build paper-writing evidence report (support/contradict/uncertain + gaps) from bundle JSON."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def classify(p: Dict[str, Any]) -> str:
    s = float(p.get("support_score") or 0)
    c = float(p.get("contradiction_score") or 0)
    if s >= c + 0.08:
        return "support"
    if c >= s + 0.08:
        return "contradict"
    return "uncertain"


def first_author(authors: Any) -> str:
    if isinstance(authors, list) and authors:
        return str(authors[0])
    return "NA"


def fmt_ref(p: Dict[str, Any]) -> str:
    author = first_author(p.get("authors"))
    year = p.get("year") or "n.d."
    title = p.get("title") or "(no title)"
    doi = p.get("doi") or "(no DOI)"
    url = p.get("url") or ""
    return f"- {author} ({year}). {title}. DOI: {doi}. Link: {url}".strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    data = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    paper_block = data.get("papers") or {}
    papers: List[Dict[str, Any]] = paper_block.get("papers") or []
    claim = paper_block.get("claim") or ""
    hypothesis = paper_block.get("hypothesis") or ""
    warnings = paper_block.get("warnings") or []

    scored = sorted(papers, key=lambda x: float(x.get("evidence_score") or 0), reverse=True)
    labeled = [(classify(p), p) for p in scored]

    support = [p for k, p in labeled if k == "support"][: args.top]
    contradict = [p for k, p in labeled if k == "contradict"][: args.top]
    uncertain = [p for k, p in labeled if k == "uncertain"][: args.top]

    gaps = []
    if not support:
        gaps.append("직접 지지 근거가 부족합니다. query/entity를 구체화하세요.")
    if not contradict:
        gaps.append("반증 논문이 거의 없습니다. 반증 검색 쿼리를 별도로 추가하세요.")
    if sum(1 for p in scored if p.get("doi")) < max(3, min(10, len(scored))):
        gaps.append("DOI 없는 결과 비율이 높습니다. PubMed/OpenAlex 중심 재검색이 필요합니다.")

    lines = []
    lines.append("# Claim-Level Evidence Report")
    lines.append("")
    lines.append(f"- Claim: {claim}")
    lines.append(f"- Hypothesis: {hypothesis}")
    lines.append(f"- Total candidates: {len(scored)}")
    lines.append("")

    lines.append("## Supporting papers")
    if support:
        lines.extend([fmt_ref(p) for p in support])
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Contradicting papers")
    if contradict:
        lines.extend([fmt_ref(p) for p in contradict])
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Uncertain papers")
    if uncertain:
        lines.extend([fmt_ref(p) for p in uncertain])
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Gaps / Next actions")
    if gaps:
        lines.extend([f"- {g}" for g in gaps])
    else:
        lines.append("- 현재 기준으로 support/contradict 균형이 적절합니다.")
    lines.append("")

    if warnings:
        lines.append("## Warnings")
        lines.extend([f"- {w}" for w in warnings])
        lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
