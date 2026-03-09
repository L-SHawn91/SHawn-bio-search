#!/usr/bin/env python3
"""Publication trend analysis using PubMed E-utilities (no EDirect required)."""

import argparse
import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List


def get_count(query: str, year: int) -> int:
    params = {
        "db": "pubmed",
        "term": query,
        "mindate": str(year),
        "maxdate": str(year),
        "datetype": "pdat",
        "retmode": "json",
        "retmax": "0",
    }
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return int(data.get("esearchresult", {}).get("count", "0"))


def run(query: str, start_year: int, end_year: int) -> List[Dict[str, int]]:
    rows = []
    cum = 0
    for y in range(start_year, end_year + 1):
        c = get_count(query, y)
        cum += c
        rows.append({"year": y, "count": c, "cumulative": cum})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="PubMed publication trends")
    parser.add_argument("--query", required=True)
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = run(args.query, args.start_year, args.end_year)
    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["year", "count", "cumulative"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    peak = sorted(rows, key=lambda r: r["count"], reverse=True)[:3]
    print(f"saved: {out}")
    print("top_years:")
    for p in peak:
        print(f"{p['year']}\t{p['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
