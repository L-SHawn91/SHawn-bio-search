"""Planning and execution for the download pipeline.

`plan_from_bundle` resolves URLs and writes a manifest.
`execute_manifest` walks the manifest and fetches everything that is ready.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .dataset_resolver import enumerate_dataset_files
from .fetcher import download_to_path
from .manifest import (
    find_entry,
    load_manifest,
    merge_entry,
    new_manifest,
    save_manifest,
)
from .resolver import resolve_pdf_url

DEFAULT_MAX_FILE_MB = 500
DEFAULT_WORKERS = 4


# ---------------------------- helpers ----------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str, fallback: str = "x") -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = _SAFE_NAME.sub("_", value).strip("._-")
    return value or fallback


def _short_id(record: Dict[str, Any]) -> str:
    doi = (record.get("doi") or "").strip()
    if doi:
        return _slug(doi.split("/")[-1])[:12] or hashlib.sha1(doi.encode()).hexdigest()[:8]
    url = (record.get("url") or "").strip()
    if url:
        return hashlib.sha1(url.encode()).hexdigest()[:8]
    return hashlib.sha1(repr(sorted(record.items())).encode()).hexdigest()[:8]


_FORBIDDEN_FN = re.compile(r"[\x00-\x1f/\\:*?\"<>|]")


def _paper_filename(record: Dict[str, Any]) -> str:
    """Zotero-standard filename: 'Author 등 - YEAR - Title.pdf' (default).

    Falls back to short-id form when title or year is missing.
    Set env SHAWN_FILENAME_STYLE=canonical to revert to legacy
    'author_year_shortid.pdf'.
    """
    import os as _os
    authors = record.get("authors") or []
    first = ""
    if authors:
        first_full = str(authors[0]).strip()
        # surname (last token after splitting "Family, Given" or "Given Family")
        if "," in first_full:
            first = first_full.split(",")[0].strip()
        else:
            first = first_full.split(" ")[-1]
    year = str(record.get("year") or "")
    title = (record.get("title") or "").strip()

    style = _os.environ.get("SHAWN_FILENAME_STYLE", "zotero").lower()
    if style == "canonical" or not title or not year:
        # legacy / fallback
        y = year or "n.d."
        return f"{_slug(first or 'anon', 'anon')}_{_slug(y, 'n.d.')}_{_short_id(record)}.pdf"

    # Zotero-standard
    fa = first or "Anon"
    multi_marker = " 등" if len(authors) > 1 else ""
    title_clean = _FORBIDDEN_FN.sub("", title.replace("\n", " "))
    title_clean = re.sub(r"\s+", " ", title_clean).strip()
    if len(title_clean) > 90:
        title_clean = title_clean[:90].rsplit(" ", 1)[0]
    fa_clean = _FORBIDDEN_FN.sub("", fa)[:60]
    return f"{fa_clean}{multi_marker} - {year} - {title_clean}.pdf"


def _resolve_collision(dest_root: Path, rel: Path) -> Path:
    candidate = dest_root / rel
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    i = 2
    while True:
        alt = parent / f"{stem}_{i}{suffix}"
        if not alt.exists():
            return alt
        i += 1


def _paper_key(record: Dict[str, Any]) -> str:
    for k in ("doi", "pmid", "id", "url"):
        v = record.get(k)
        if v:
            return str(v)
    return hashlib.sha1(repr(sorted(record.items())).encode()).hexdigest()


def _dataset_key(record: Dict[str, Any], filename: str) -> str:
    repo = record.get("repository") or "unknown"
    acc = record.get("accession") or record.get("id") or "unknown"
    return f"{repo}:{acc}:{filename}"


def _mb_to_bytes(mb: Optional[float]) -> Optional[int]:
    if mb is None:
        return None
    return int(mb * 1024 * 1024)


def _load_bundle(bundle_path: Path) -> Dict[str, Any]:
    with Path(bundle_path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"bundle must be a JSON object: {bundle_path}")
    return data


def _extract_papers(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    papers = bundle.get("papers")
    if isinstance(papers, dict):
        papers = papers.get("papers")
    if isinstance(papers, list):
        return [p for p in papers if isinstance(p, dict)]
    return []


def _extract_datasets(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    datasets = bundle.get("datasets")
    if isinstance(datasets, dict):
        datasets = datasets.get("datasets")
    if isinstance(datasets, list):
        return [d for d in datasets if isinstance(d, dict)]
    return []


# ---------------------------- planning ----------------------------


def _plan_paper(
    record: Dict[str, Any],
    *,
    dest_root: Path,
    use_unpaywall: bool,
) -> Dict[str, Any]:
    key = _paper_key(record)
    filename = _paper_filename(record)
    dest_rel = Path("papers") / filename
    url, resolution = resolve_pdf_url(record, use_unpaywall=use_unpaywall)

    if resolution == "paywalled":
        status = "paywalled"
    elif resolution == "not-article":
        status = "skipped"
    elif not url:
        status = "no-url"
    else:
        status = "planned"

    return {
        "kind": "paper",
        "key": key,
        "source": record.get("source") or "",
        "title": record.get("title") or "",
        "doi": record.get("doi") or "",
        "planned_url": url,
        "resolution": resolution,
        "dest_path": str(dest_rel),
        "status": status,
        "bytes": None,
        "sha256": "",
        "http_status": None,
        "error": None,
        "planned_at": _now_iso(),
        "attempted_at": None,
    }


def _plan_dataset(record: Dict[str, Any], *, dest_root: Path) -> List[Dict[str, Any]]:
    repo = str(record.get("repository") or "unknown").lower()
    acc = str(record.get("accession") or record.get("id") or "unknown")
    outcome = enumerate_dataset_files(record)

    entries: List[Dict[str, Any]] = []
    now = _now_iso()

    if outcome["kind"] == "external":
        entries.append({
            "kind": "dataset_instruction",
            "key": f"{repo}:{acc}",
            "repository": repo,
            "accession": acc,
            "title": record.get("title") or "",
            "tool": outcome.get("tool"),
            "args": outcome.get("args") or [],
            "note": outcome.get("note") or "",
            "status": "requires_external_tool",
            "planned_at": now,
        })
        return entries

    if outcome["kind"] == "no-url":
        entries.append({
            "kind": "dataset_instruction",
            "key": f"{repo}:{acc}",
            "repository": repo,
            "accession": acc,
            "title": record.get("title") or "",
            "tool": None,
            "args": [],
            "note": outcome.get("note") or "",
            "status": "no-url",
            "planned_at": now,
        })
        return entries

    files = outcome.get("files") or []
    if not files:
        entries.append({
            "kind": "dataset_instruction",
            "key": f"{repo}:{acc}",
            "repository": repo,
            "accession": acc,
            "title": record.get("title") or "",
            "tool": None,
            "args": [],
            "note": "No downloadable files listed by the repository.",
            "status": "no-url",
            "planned_at": now,
        })
        return entries

    for f in files:
        name = _slug(f.get("name") or "file", "file")
        dest_rel = Path("datasets") / _slug(repo) / _slug(acc) / name
        entry = {
            "kind": "dataset_file",
            "key": _dataset_key(record, name),
            "repository": repo,
            "accession": acc,
            "filename": name,
            "planned_url": f.get("url") or "",
            "size_hint": f.get("size"),
            "checksum_hint": f.get("checksum") or "",
            "dest_path": str(dest_rel),
            "status": "planned" if f.get("url") else "no-url",
            "bytes": None,
            "sha256": "",
            "http_status": None,
            "error": None,
            "planned_at": now,
            "attempted_at": None,
        }
        if f.get("note"):
            entry["note"] = f["note"]
        entries.append(entry)
    return entries


def plan_from_bundle(
    bundle_path: Path,
    dest_root: Path,
    *,
    kinds: Iterable[str] = ("papers", "datasets"),
    use_unpaywall: bool = True,
    max_file_mb: Optional[float] = DEFAULT_MAX_FILE_MB,
    workers: int = DEFAULT_WORKERS,
    sources: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Build a manifest describing what would be downloaded."""
    bundle = _load_bundle(Path(bundle_path))
    dest_root = Path(dest_root)

    manifest = new_manifest(
        source_bundle=str(bundle_path),
        options={
            "max_file_mb": max_file_mb,
            "workers": workers,
            "kinds": list(kinds),
            "use_unpaywall": use_unpaywall,
            "sources": list(sources) if sources else None,
        },
    )

    kinds_set = {k.strip().lower() for k in kinds}
    source_filter = {s.strip().lower() for s in sources} if sources else None

    if "papers" in kinds_set:
        for rec in _extract_papers(bundle):
            if source_filter and (rec.get("source") or "").lower() not in source_filter:
                continue
            merge_entry(manifest, _plan_paper(rec, dest_root=dest_root, use_unpaywall=use_unpaywall))

    if "datasets" in kinds_set:
        for rec in _extract_datasets(bundle):
            if source_filter and (rec.get("repository") or "").lower() not in source_filter:
                continue
            for entry in _plan_dataset(rec, dest_root=dest_root):
                merge_entry(manifest, entry)

    return manifest


# ---------------------------- execution ----------------------------


def _execute_paper_entry(
    entry: Dict[str, Any],
    *,
    dest_root: Path,
    max_bytes: Optional[int],
) -> Dict[str, Any]:
    if entry.get("status") not in {"planned", "failed"}:
        return entry
    url = entry.get("planned_url") or ""
    if not url:
        entry["status"] = "no-url"
        entry["attempted_at"] = _now_iso()
        return entry

    dest = _resolve_collision(dest_root, Path(entry["dest_path"]))
    result = download_to_path(url, dest, max_bytes=max_bytes, expect_pdf=True)
    entry.update({
        "dest_path": str(dest.relative_to(dest_root)),
        "status": result["status"],
        "bytes": result["bytes"],
        "sha256": result["sha256"],
        "http_status": result["http_status"],
        "error": result["error"],
        "attempted_at": _now_iso(),
    })
    return entry


def _execute_dataset_entry(
    entry: Dict[str, Any],
    *,
    dest_root: Path,
    max_bytes: Optional[int],
) -> Dict[str, Any]:
    if entry.get("status") not in {"planned", "failed"}:
        return entry
    url = entry.get("planned_url") or ""
    if not url:
        entry["status"] = "no-url"
        entry["attempted_at"] = _now_iso()
        return entry
    dest = _resolve_collision(dest_root, Path(entry["dest_path"]))
    result = download_to_path(url, dest, max_bytes=max_bytes, expect_pdf=False)
    entry.update({
        "dest_path": str(dest.relative_to(dest_root)),
        "status": result["status"],
        "bytes": result["bytes"],
        "sha256": result["sha256"],
        "http_status": result["http_status"],
        "error": result["error"],
        "attempted_at": _now_iso(),
    })
    return entry


def execute_manifest(
    manifest_path: Path,
    dest_root: Path,
    *,
    max_file_mb: Optional[float] = DEFAULT_MAX_FILE_MB,
    workers: int = DEFAULT_WORKERS,
    log_path: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    manifest_path = Path(manifest_path)
    dest_root = Path(dest_root)
    manifest = load_manifest(manifest_path)
    max_bytes = _mb_to_bytes(max_file_mb)

    tasks: List[Dict[str, Any]] = []
    for entry in manifest["entries"]:
        if entry.get("kind") == "paper":
            tasks.append(entry)
        elif entry.get("kind") == "dataset_file":
            tasks.append(entry)

    if dry_run:
        return manifest

    def _run(entry: Dict[str, Any]) -> Dict[str, Any]:
        if entry.get("kind") == "paper":
            return _execute_paper_entry(entry, dest_root=dest_root, max_bytes=max_bytes)
        return _execute_dataset_entry(entry, dest_root=dest_root, max_bytes=max_bytes)

    log_fh = None
    if log_path is not None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = log_path.open("a", encoding="utf-8")

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_run, entry): entry for entry in tasks}
            for fut in as_completed(futures):
                updated = fut.result()
                merge_entry(manifest, updated)
                save_manifest(manifest_path, manifest)
                if log_fh is not None:
                    log_fh.write(json.dumps({
                        "at": _now_iso(),
                        "kind": updated.get("kind"),
                        "key": updated.get("key"),
                        "status": updated.get("status"),
                        "bytes": updated.get("bytes"),
                        "error": updated.get("error"),
                    }, ensure_ascii=False) + "\n")
                    log_fh.flush()
    finally:
        if log_fh is not None:
            log_fh.close()

    return manifest


def plan_and_execute(
    bundle_path: Path,
    dest_root: Path,
    *,
    kinds: Iterable[str] = ("papers", "datasets"),
    use_unpaywall: bool = True,
    max_file_mb: Optional[float] = DEFAULT_MAX_FILE_MB,
    workers: int = DEFAULT_WORKERS,
    sources: Optional[Iterable[str]] = None,
    manifest_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    dest_root = Path(dest_root)
    manifest_path = Path(manifest_path or dest_root / "manifest.json")
    manifest = plan_from_bundle(
        bundle_path,
        dest_root,
        kinds=kinds,
        use_unpaywall=use_unpaywall,
        max_file_mb=max_file_mb,
        workers=workers,
        sources=sources,
    )
    save_manifest(manifest_path, manifest)
    return execute_manifest(
        manifest_path,
        dest_root,
        max_file_mb=max_file_mb,
        workers=workers,
        log_path=log_path,
    )


# ---------------------------- CLI ----------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shawn-bio-download",
        description="Download OA papers and dataset files from a shawn-bio-search bundle.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--bundle", type=Path, help="Path to a search_bundle JSON file.")
    src.add_argument("--execute", type=Path, help="Execute an existing manifest.json.")

    p.add_argument("--dest", type=Path, required=True, help="Download root directory.")
    p.add_argument(
        "--kind",
        default="papers,datasets",
        help="Comma-separated kinds to plan: papers,datasets (default both).",
    )
    p.add_argument("--plan-only", action="store_true", help="Write manifest but don't download.")
    p.add_argument(
        "--max-file-mb",
        type=float,
        default=DEFAULT_MAX_FILE_MB,
        help="Per-file size cap in MB (default 500). Use --allow-large to disable.",
    )
    p.add_argument("--allow-large", action="store_true", help="Disable the per-file size cap.")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel downloads (default 4).")
    p.add_argument("--no-unpaywall", action="store_true", help="Skip Unpaywall OA fallback.")
    p.add_argument(
        "--sources",
        default="",
        help="Comma-separated filter for paper sources or dataset repositories.",
    )
    p.add_argument("--manifest", type=Path, default=None, help="Manifest path (default <dest>/manifest.json).")
    p.add_argument("--log", type=Path, default=None, help="Append-only JSONL log path.")
    p.add_argument("--dry-run", action="store_true", help="Plan + read manifest but don't fetch.")
    return p


def main_cli(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    kinds = [k.strip() for k in (args.kind or "").split(",") if k.strip()]
    sources = [s.strip() for s in (args.sources or "").split(",") if s.strip()] or None
    max_mb = None if args.allow_large else args.max_file_mb
    dest_root: Path = args.dest
    dest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (dest_root / "manifest.json")
    log_path = args.log

    if args.execute is not None:
        execute_manifest(
            args.execute,
            dest_root,
            max_file_mb=max_mb,
            workers=args.workers,
            log_path=log_path,
            dry_run=args.dry_run,
        )
        return 0

    manifest = plan_from_bundle(
        args.bundle,
        dest_root,
        kinds=kinds,
        use_unpaywall=not args.no_unpaywall,
        max_file_mb=max_mb,
        workers=args.workers,
        sources=sources,
    )
    save_manifest(manifest_path, manifest)

    if args.plan_only or args.dry_run:
        _print_plan_summary(manifest, manifest_path)
        return 0

    execute_manifest(
        manifest_path,
        dest_root,
        max_file_mb=max_mb,
        workers=args.workers,
        log_path=log_path,
    )
    _print_plan_summary(load_manifest(manifest_path), manifest_path)
    return 0


def _print_plan_summary(manifest: Dict[str, Any], manifest_path: Path) -> None:
    counts: Dict[str, int] = {}
    for e in manifest.get("entries", []):
        counts[e.get("status", "unknown")] = counts.get(e.get("status", "unknown"), 0) + 1
    print(f"manifest: {manifest_path}")
    print(f"entries: {len(manifest.get('entries', []))}")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")


if __name__ == "__main__":
    sys.exit(main_cli())
