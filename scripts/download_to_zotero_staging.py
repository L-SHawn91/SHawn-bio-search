#!/usr/bin/env python3
"""Download safe paper candidates into a Zotero-root staging subtree.

This script is intentionally conservative:
- reads PAPER_CANDIDATE_MASTER.tsv + SEARCH_RESULTS.json
- downloads only records classified as safe_auto by default
- requires explicit --zotero-root or ZOTERO_ROOT
- writes into Zotero staging subdirs, not arbitrary final library folders
- skips existing DOI/title-based duplicates in the target subtree
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "").strip())
    return text[:160].strip("_") or "paper"


def _load_candidates(tsv_path: Path) -> list[Dict[str, str]]:
    with tsv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter='\t'))


def _load_search_results(json_path: Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {r.get("citation_key"): r for r in data.get("results") or []}


def _target_filename(result: Dict[str, Any]) -> str:
    doi = _safe_name((result.get("doi") or "NO_DOI").replace("/", "_"))
    authors = result.get("authors") or []
    first_author = _safe_name(authors[0] if authors else "Unknown")
    year = str(result.get("year") or "nd")
    title = _safe_name(result.get("title") or "paper")[:80]
    return f"{doi}__{first_author}_{year}__{title}.pdf"


def _already_exists(target_dir: Path, result: Dict[str, Any]) -> bool:
    doi_tok = _normalize(result.get("doi") or "")
    title_tok = _normalize(result.get("title") or "")[:40]
    for p in target_dir.rglob("*.pdf"):
        stem = _normalize(p.stem)
        if doi_tok and doi_tok in stem:
            return True
        if title_tok and len(title_tok) >= 24 and title_tok[:24] in stem:
            return True
    return False


def _resolve_zotero_root(explicit: str = "") -> str:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_root = os.getenv("ZOTERO_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _download(url: str, timeout: int = 30) -> Tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "SHawn-bio-search/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        content_type = (r.headers.get("Content-Type") or "").lower()
    return data, content_type


def _looks_like_pdf(data: bytes, content_type: str) -> bool:
    if data[:5] == b'%PDF-':
        return True
    if 'pdf' in (content_type or ''):
        return True
    return False


def _append_manifest_row(path: Path, row: Dict[str, str]) -> None:
    exists = path.exists()
    with path.open('a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'citation_key', 'routing_class', 'status', 'url', 'output_path',
            'content_type', 'bytes', 'note'
        ], delimiter='\t')
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="Download safe candidates into Zotero staging")
    ap.add_argument("--paper-candidate-master", required=True)
    ap.add_argument("--search-results", required=True)
    ap.add_argument("--zotero-root", default=os.getenv("ZOTERO_ROOT", ""))
    ap.add_argument("--routing-class", default="safe_auto", choices=["safe_auto", "review_first"])
    ap.add_argument("--manifest-path", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    zotero_root = _resolve_zotero_root(args.zotero_root)
    if not zotero_root:
        print("ERROR: Zotero root not set or not found. Use --zotero-root or set ZOTERO_ROOT.", file=sys.stderr)
        return 2

    candidates = _load_candidates(Path(args.paper_candidate_master))
    results_by_key = _load_search_results(Path(args.search_results))

    downloaded = 0
    skipped = 0
    target_root = Path(zotero_root)
    manifest_path = Path(args.manifest_path) if args.manifest_path else (target_root / "_incoming_shawn_bio_search" / "DOWNLOAD_MANIFEST.tsv")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    for row in candidates:
        if row.get("download_routing_class") != args.routing_class:
            continue
        key = row.get("citation_key") or ""
        result = results_by_key.get(key)
        if not result:
            skipped += 1
            continue
        pdf_url = ((result.get("access") or {}).get("pdf_url") or "").strip()
        if not pdf_url:
            skipped += 1
            continue
        subdir = row.get("target_zotero_subdir") or "_incoming_shawn_bio_search/review_needed"
        out_dir = target_root / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        if _already_exists(out_dir, result):
            print(f"skip-existing\t{key}\t{out_dir}")
            _append_manifest_row(manifest_path, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': key,
                'routing_class': args.routing_class,
                'status': 'skip-existing',
                'url': pdf_url,
                'output_path': str(out_dir),
                'content_type': '',
                'bytes': '0',
                'note': 'duplicate heuristic match',
            })
            skipped += 1
            continue
        out_path = out_dir / _target_filename(result)
        if args.dry_run:
            print(f"dry-run\t{key}\t{pdf_url}\t{out_path}")
            _append_manifest_row(manifest_path, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': key,
                'routing_class': args.routing_class,
                'status': 'dry-run',
                'url': pdf_url,
                'output_path': str(out_path),
                'content_type': '',
                'bytes': '0',
                'note': 'planned download only',
            })
            downloaded += 1
            continue
        try:
            data, content_type = _download(pdf_url)
            if not _looks_like_pdf(data, content_type):
                print(f"blocked-nonpdf\t{key}\t{content_type}\t{pdf_url}")
                _append_manifest_row(manifest_path, {
                    'timestamp': datetime.now().astimezone().isoformat(),
                    'citation_key': key,
                    'routing_class': args.routing_class,
                    'status': 'blocked-nonpdf',
                    'url': pdf_url,
                    'output_path': str(out_path),
                    'content_type': content_type,
                    'bytes': str(len(data)),
                    'note': 'response does not look like a PDF',
                })
                skipped += 1
                continue
            out_path.write_bytes(data)
            print(f"downloaded\t{key}\t{out_path}")
            _append_manifest_row(manifest_path, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': key,
                'routing_class': args.routing_class,
                'status': 'downloaded',
                'url': pdf_url,
                'output_path': str(out_path),
                'content_type': content_type,
                'bytes': str(len(data)),
                'note': 'ok',
            })
            downloaded += 1
        except Exception as exc:
            print(f"failed\t{key}\t{exc}")
            _append_manifest_row(manifest_path, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': key,
                'routing_class': args.routing_class,
                'status': 'failed',
                'url': pdf_url,
                'output_path': str(out_path),
                'content_type': '',
                'bytes': '0',
                'note': str(exc),
            })
            skipped += 1

    print(f"summary\tdownloaded={downloaded}\tskipped={skipped}\tmanifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
