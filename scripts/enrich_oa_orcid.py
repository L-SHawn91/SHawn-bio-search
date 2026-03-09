#!/usr/bin/env python3
"""Enrich bundle papers with Unpaywall OA metadata and ORCID author matches (best-effort)."""

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple


def http_json(url: str, headers: Dict[str, str] | None = None, timeout: int = 12) -> Dict[str, Any] | None:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        return json.loads(data.decode("utf-8", errors="ignore"))
    except Exception:
        return None


def parse_author(author: str) -> Tuple[str, str]:
    s = (author or "").strip()
    if not s:
        return "", ""
    if "," in s:
        family, given = [x.strip() for x in s.split(",", 1)]
        return given, family
    parts = s.split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def enrich_unpaywall(paper: Dict[str, Any], email: str, cache: Dict[str, Any]) -> Dict[str, Any]:
    doi = (paper.get("doi") or "").strip()
    if not doi:
        paper["oa_status"] = "unknown"
        return paper

    k = doi.lower()
    if k not in cache:
        url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
        cache[k] = http_json(url) or {}
        time.sleep(0.05)

    d = cache[k]
    paper["oa_status"] = d.get("oa_status") or "unknown"
    best = d.get("best_oa_location") or {}
    paper["oa_pdf_url"] = best.get("url_for_pdf") or best.get("url") or ""
    paper["oa_license"] = best.get("license") or ""
    paper["is_oa"] = bool(d.get("is_oa"))
    return paper


def enrich_orcid(paper: Dict[str, Any], preferred_orcid: str, cache: Dict[str, Any]) -> Dict[str, Any]:
    authors = paper.get("authors") or []
    if not isinstance(authors, list) or not authors:
        paper["orcid_matches"] = []
        return paper

    first = str(authors[0])
    given, family = parse_author(first)
    if not family:
        paper["orcid_matches"] = []
        return paper

    query = f"family-name:{family}"
    if given:
        query += f" AND given-names:{given.split()[0]}"

    qk = query.lower()
    if qk not in cache:
        url = "https://pub.orcid.org/v3.0/expanded-search/?q=" + urllib.parse.quote(query)
        cache[qk] = http_json(url, headers={"Accept": "application/json"}) or {}
        time.sleep(0.05)

    resp = cache[qk]
    out = []
    for r in (resp.get("expanded-result") or [])[:5]:
        oid = r.get("orcid-id") or ""
        gn = r.get("given-names") or ""
        fn = r.get("family-names") or ""
        out.append({
            "orcid": oid,
            "given": gn,
            "family": fn,
            "preferred_match": bool(preferred_orcid and oid == preferred_orcid),
        })
    paper["orcid_matches"] = out
    paper["orcid_query"] = query
    return paper


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-unpaywall", action="store_true")
    ap.add_argument("--with-orcid", action="store_true")
    ap.add_argument("--unpaywall-email", default=os.getenv("UNPAYWALL_EMAIL", ""))
    ap.add_argument("--orcid-preferred-id", default=os.getenv("ORCID_PREFERRED_ID", ""))
    args = ap.parse_args()

    bundle_path = Path(args.bundle)
    out_path = Path(args.out)
    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    papers = ((data.get("papers") or {}).get("papers") or [])

    unpaywall_cache: Dict[str, Any] = {}
    orcid_cache: Dict[str, Any] = {}
    warnings: List[str] = []

    if args.with_unpaywall and not args.unpaywall_email:
        warnings.append("unpaywall skipped: UNPAYWALL_EMAIL missing")
    if args.with_orcid and not args.orcid_preferred_id:
        warnings.append("orcid preferred id missing: running best-effort author search only")

    enriched = []
    for p in papers:
        x = dict(p)
        if args.with_unpaywall and args.unpaywall_email:
            x = enrich_unpaywall(x, args.unpaywall_email, unpaywall_cache)
        if args.with_orcid:
            x = enrich_orcid(x, args.orcid_preferred_id, orcid_cache)
        enriched.append(x)

    (data.setdefault("papers", {}))["papers"] = enriched
    if warnings:
        (data["papers"].setdefault("warnings", [])).extend(warnings)

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
