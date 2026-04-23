#!/usr/bin/env python3
"""Promote downloaded PDFs from Zotero incoming staging into final papers shelves.

Conservative behavior:
- reads DOWNLOAD_MANIFEST.tsv
- promotes only records with status=downloaded
- verifies file exists and starts with %PDF-
- skips likely duplicates in final destination
- default final destination is papers/_promoted_shawn_bio_search unless explicitly overridden
"""

import argparse
import csv
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _resolve_zotero_root(explicit: str = "") -> str:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_root = os.getenv("ZOTERO_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend([
        Path('/home/mdge/Clouds/onedrive/Papers/Zotero/papers'),
        Path('/home/mdge/Papers/Zotero/papers'),
        Path('/media/mdge/4TB_MDGE/Papers/Zotero/papers'),
        Path('/home/mdge/Zotero/papers'),
    ])
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _load_manifest(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f, delimiter='\t'))


def _looks_like_pdf(path: Path) -> bool:
    try:
        return path.exists() and path.read_bytes()[:5] == b'%PDF-'
    except Exception:
        return False


def _already_exists(target_dir: Path, source_file: Path) -> bool:
    stem_tok = _normalize(source_file.stem)
    for p in target_dir.rglob('*.pdf'):
        if stem_tok and stem_tok in _normalize(p.stem):
            return True
    return False


def _append_log(path: Path, row: Dict[str, str]) -> None:
    exists = path.exists()
    with path.open('a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'citation_key', 'source_stage_path', 'final_path',
            'destination_policy', 'status', 'note'
        ], delimiter='\t')
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description='Promote downloaded PDFs from incoming staging into final papers folders')
    ap.add_argument('--zotero-root', default=os.getenv('ZOTERO_ROOT', ''))
    ap.add_argument('--manifest-path', default='')
    ap.add_argument('--destination-subdir', default='_promoted_shawn_bio_search')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    zotero_root = _resolve_zotero_root(args.zotero_root)
    if not zotero_root:
        print('ERROR: Zotero root not set or not found.', file=sys.stderr)
        return 2

    root = Path(zotero_root)
    manifest_path = Path(args.manifest_path) if args.manifest_path else (root / '_incoming_shawn_bio_search' / 'DOWNLOAD_MANIFEST.tsv')
    promotion_log = root / '_incoming_shawn_bio_search' / 'PROMOTION_LOG.tsv'
    final_dir = root / args.destination_subdir
    final_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_manifest(manifest_path)
    promoted = 0
    skipped = 0

    for row in rows:
        if row.get('status') != 'downloaded':
            continue
        citation_key = row.get('citation_key') or ''
        src = Path(row.get('output_path') or '')
        if not src.exists():
            _append_log(promotion_log, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': citation_key,
                'source_stage_path': str(src),
                'final_path': '',
                'destination_policy': args.destination_subdir,
                'status': 'missing-source',
                'note': 'downloaded manifest entry but file missing',
            })
            skipped += 1
            continue
        if not _looks_like_pdf(src):
            _append_log(promotion_log, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': citation_key,
                'source_stage_path': str(src),
                'final_path': '',
                'destination_policy': args.destination_subdir,
                'status': 'blocked-nonpdf',
                'note': 'source file does not look like PDF',
            })
            skipped += 1
            continue
        dest = final_dir / src.name
        if _already_exists(final_dir, src):
            _append_log(promotion_log, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': citation_key,
                'source_stage_path': str(src),
                'final_path': str(dest),
                'destination_policy': args.destination_subdir,
                'status': 'skip-existing',
                'note': 'duplicate heuristic match in final destination',
            })
            skipped += 1
            continue
        if args.dry_run:
            print(f'dry-run\t{citation_key}\t{src}\t{dest}')
            _append_log(promotion_log, {
                'timestamp': datetime.now().astimezone().isoformat(),
                'citation_key': citation_key,
                'source_stage_path': str(src),
                'final_path': str(dest),
                'destination_policy': args.destination_subdir,
                'status': 'dry-run',
                'note': 'planned promotion only',
            })
            promoted += 1
            continue
        shutil.move(str(src), str(dest))
        print(f'promoted\t{citation_key}\t{dest}')
        _append_log(promotion_log, {
            'timestamp': datetime.now().astimezone().isoformat(),
            'citation_key': citation_key,
            'source_stage_path': str(src),
            'final_path': str(dest),
            'destination_policy': args.destination_subdir,
            'status': 'promoted',
            'note': 'ok',
        })
        promoted += 1

    print(f'summary\tpromoted={promoted}\tskipped={skipped}\tlog={promotion_log}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
