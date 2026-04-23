#!/usr/bin/env python3
"""Extract methods/supplement evidence candidates from SHawn-bio-search outputs."""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from pypdf import PdfReader

HEADERS = {"User-Agent": "SHawn-bio-search/1.0"}


def _load_candidates(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("items", [])


def _fetch_text(url: str, timeout: int = 20) -> Tuple[str, str]:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    content_type = (r.headers.get("content-type") or "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        tmp = Path("/tmp/shawn_bio_extract_tmp.pdf")
        tmp.write_bytes(r.content)
        reader = PdfReader(str(tmp))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return "pdf", text
    text = r.text
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return "html", text


def _extract_relevant_snippets(text: str, terms: List[str], max_snippets: int = 10) -> List[str]:
    snippets = []
    lowered = text.lower()
    for term in terms:
        idx = lowered.find(term.lower())
        if idx >= 0:
            start = max(0, idx - 220)
            end = min(len(text), idx + 420)
            snippet = text[start:end].strip()
            if snippet and snippet not in snippets:
                snippets.append(snippet)
    return snippets[:max_snippets]


def _analyze_item(item: Dict[str, Any], terms: List[str]) -> Dict[str, Any]:
    hints = item.get("extraction_hints") or {}
    urls = []
    urls.extend(hints.get("supplement_candidates") or [])
    urls.extend(hints.get("fulltext_candidates") or [])
    urls.extend(hints.get("parent_paper_candidates") or [])

    checked = []
    snippets = []
    matched_terms = set()

    for url in urls[:8]:
        try:
            kind, text = _fetch_text(url)
            checked.append({"url": url, "kind": kind, "status": "ok"})
            for term in terms:
                if term.lower() in text.lower():
                    matched_terms.add(term.lower())
            snippets.extend(_extract_relevant_snippets(text, terms))
            if len(matched_terms) == len(terms):
                break
        except Exception as exc:
            checked.append({"url": url, "status": f"failed: {exc}"})

    return {
        "title": item.get("title"),
        "doi": item.get("doi"),
        "source": item.get("source"),
        "checked_urls": checked,
        "matched_terms": sorted(matched_terms),
        "all_terms_present": len(matched_terms) == len(terms),
        "snippets": snippets[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to EXTRACTION_CANDIDATES.json")
    ap.add_argument("--terms", default="", help="Comma-separated terms to verify")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    items = _load_candidates(args.input)
    results = [_analyze_item(item, terms) for item in items]
    payload = {
        "terms": terms,
        "count": len(results),
        "full_match_count": sum(1 for r in results if r["all_terms_present"]),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
