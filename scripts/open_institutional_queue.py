#!/usr/bin/env python3
"""Open institutional-access queue records in browser batches.

This script only opens legitimate DOI/publisher pages in the user's browser and
writes an audit log. It does not extract browser cookies, credentials, or PDFs.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List


REPO = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = REPO / "outputs/dhcr24_260427/DHCR24_INSTITUTIONAL_ACCESS_READY_260427.tsv"
DEFAULT_OUT_DIR = REPO / "outputs/dhcr24_260427"
DEFAULT_STATUSES = ["institutional_access_ready"]
ACTIONABLE_STATUSES = [
    "institutional_access_ready",
    "manual_review_institutional_access_available",
]


def _load_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _write_tsv(path: Path, rows: Iterable[Dict[str, str]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _doi_url(doi: str) -> str:
    doi = doi.strip()
    if doi.startswith("http://") or doi.startswith("https://"):
        return doi
    return f"https://doi.org/{doi}"


def _select_rows(rows: List[Dict[str, str]], statuses: List[str], start: int, limit: int | None) -> List[Dict[str, str]]:
    selected = [r for r in rows if (r.get("new_status") or r.get("status") or "") in statuses and r.get("doi")]
    selected = selected[start:]
    if limit is not None:
        selected = selected[:limit]
    return selected


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Open institutional-access queue DOI pages in browser batches")
    ap.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--status", action="append", default=None, help="Queue status to open; repeatable")
    ap.add_argument("--all-actionable", action="store_true", help="Open ready and manual-review institutional records")
    ap.add_argument("--start", type=int, default=0, help="Offset within selected queue rows")
    ap.add_argument("--limit", type=int, default=10, help="Max rows to open; use 0 for all selected rows")
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=2.0, help="Seconds between batches")
    ap.add_argument("--browser-command", default="xdg-open")
    ap.add_argument("--dry-run", action="store_true")
    return ap


def main() -> int:
    args = build_arg_parser().parse_args()
    statuses = ACTIONABLE_STATUSES if args.all_actionable else (args.status or DEFAULT_STATUSES)
    limit = None if args.limit == 0 else args.limit
    rows = _select_rows(_load_rows(args.queue), statuses=statuses, start=args.start, limit=limit)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = args.out_dir / f"institutional_browser_open_audit_{stamp}.tsv"
    audit_rows: List[Dict[str, str]] = []

    for i, row in enumerate(rows, 1):
        url = _doi_url(row.get("doi", ""))
        action = "dry_run"
        error = ""
        if not args.dry_run:
            try:
                subprocess.Popen(
                    [args.browser_command, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                action = "open_requested"
            except Exception as exc:
                action = "open_failed"
                error = repr(exc)

        audit_rows.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "action": action,
                "idx": row.get("idx", ""),
                "doi": row.get("doi", ""),
                "title": row.get("title", ""),
                "new_status": row.get("new_status", ""),
                "institutional_access": row.get("institutional_access", ""),
                "access_route": row.get("access_route", "konkuk_institutional_access_linux"),
                "url": url,
                "error": error,
            }
        )

        if i % max(1, args.batch_size) == 0 and i < len(rows):
            time.sleep(max(0.0, args.sleep))

    _write_tsv(
        audit_path,
        audit_rows,
        [
            "timestamp", "action", "idx", "doi", "title", "new_status",
            "institutional_access", "access_route", "url", "error",
        ],
    )
    print(f"selected: {len(rows)}")
    print(f"saved: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
