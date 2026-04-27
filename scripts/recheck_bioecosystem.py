#!/usr/bin/env python3
"""General SHawn-bio-search ecosystem recheck wrapper.

This wrapper intentionally does not download PDFs. It performs the repeatable
audit steps that were otherwise being run as separate ad-hoc commands:

1. Load a SHawn-bio-search bundle.
2. Match candidates against the local Zotero PDF root.
3. Build an OA download plan with the package resolver and optional Unpaywall.
4. Optionally probe planned URLs with a small byte-range request to confirm PDF
   signatures without saving the file.
5. Optionally reclassify a prior institutional-access TSV after the OA recheck.

Generated files are written under --out-dir.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import ssl
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from export_dual_engine_bundle import _lookup_local_library  # noqa: E402
from shawn_bio_search.download.manifest import save_manifest  # noqa: E402
from shawn_bio_search.download.runner import plan_from_bundle  # noqa: E402
from shawn_bio_search.env import load_shawn_env  # noqa: E402


DEFAULT_ZOTERO_ROOT = Path("/home/mdge/Clouds/onedrive/Papers/Zotero/논문")
INSTITUTIONAL_ACCESS_CHOICES = ("auto", "available", "candidate", "unavailable")


def _slug(value: str, fallback: str = "project") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return value or fallback


def _default_out_dir(bundle_path: Path, project: str) -> Path:
    stem = _slug(project or bundle_path.stem, "recheck")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO / "outputs" / "recheck_bioecosystem" / f"{stem}_{stamp}"


def _resolve_institutional_access(value: str) -> str:
    if value != "auto":
        return value

    env_value = os.environ.get("SHAWN_INSTITUTIONAL_ACCESS", "").strip().lower()
    if env_value in {"available", "candidate", "unavailable"}:
        return env_value

    if platform.system().lower() == "linux":
        return "available"
    return "candidate"


def _institutional_status(institutional_access: str, old_action: str) -> str:
    if old_action.startswith("manual_review"):
        if institutional_access == "available":
            return "manual_review_institutional_access_available"
        if institutional_access == "candidate":
            return "manual_review_institutional_access_candidate"
        return "manual_review_no_institutional_access"

    if institutional_access == "available":
        return "institutional_access_ready"
    if institutional_access == "candidate":
        return "institutional_access_candidate"
    return "manual_review_no_institutional_access"


def _load_bundle(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"bundle must be a JSON object: {path}")
    return data


def _papers(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    paper_block = bundle.get("papers") or {}
    papers = paper_block.get("papers") if isinstance(paper_block, dict) else paper_block
    return [p for p in papers or [] if isinstance(p, dict)]


def _write_tsv(path: Path, rows: Iterable[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _flatten_paper_dest_paths(manifest: Dict[str, Any]) -> int:
    changed = 0
    for entry in manifest.get("entries", []):
        if entry.get("kind") != "paper":
            continue
        dest = entry.get("dest_path") or ""
        if "/" in dest:
            entry["dest_path"] = Path(dest).name
            changed += 1
    return changed


def build_local_rows(bundle: Dict[str, Any], zotero_root: Path) -> List[Dict[str, Any]]:
    pdf_files = list(zotero_root.rglob("*.pdf")) if zotero_root.exists() else []
    rows: List[Dict[str, Any]] = []
    for idx, paper in enumerate(_papers(bundle), 1):
        local = _lookup_local_library(paper, pdf_files)
        match_type = local.get("match_type") or ""
        confidence = "none"
        if match_type in {"doi", "pmid", "pmcid"}:
            confidence = "strong"
        elif match_type == "title_fuzzy":
            confidence = "candidate_review"
        rows.append(
            {
                "idx": idx,
                "title": paper.get("title") or "",
                "doi": paper.get("doi") or "",
                "pmid": paper.get("pmid") or "",
                "pmcid": paper.get("pmcid") or "",
                "source": paper.get("source") or "",
                "in_local_library": str(bool(local.get("found"))).lower(),
                "match_type": match_type,
                "match_confidence": confidence,
                "local_pdf_path": local.get("local_pdf_path") or "",
            }
        )
    return rows


def _probe_one(row: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    url = row.get("planned_url") or ""
    base = {
        "key": row.get("key") or "",
        "source": row.get("source") or "",
        "doi": row.get("doi") or "",
        "title": row.get("title") or "",
        "resolution": row.get("resolution") or "",
        "planned_url": url,
        "probe_status": "no-url",
        "http_status": "",
        "content_type": "",
        "final_url": "",
        "head4": "",
        "error": "",
    }
    if not url:
        return base

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "SHawn-bio-search/1.0",
                "Accept": "application/pdf,*/*",
                "Range": "bytes=0-3",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            data = resp.read(4)
            ctype = resp.headers.get("Content-Type", "")
            final = resp.geturl()
            final_l = final.lower()
            url_l = url.lower()
            is_pdf = data.startswith(b"%PDF")

            suspect = ""
            if "_reference.pdf" in final_l or "_reference.pdf" in url_l:
                suspect = "reference_pdf_url"
            elif "media-pack" in final_l or "media-pack" in url_l:
                suspect = "media_pack_url"
            elif not is_pdf and ("html" in ctype.lower() or final_l.startswith("https://doi.org/")):
                suspect = "landing_or_html"

            if is_pdf and not suspect:
                probe_status = "pdf_head_ok"
            elif is_pdf:
                probe_status = "pdf_head_suspect"
            else:
                probe_status = "not_pdf_head"

            base.update(
                {
                    "probe_status": probe_status,
                    "http_status": str(getattr(resp, "status", "")),
                    "content_type": ctype,
                    "final_url": final,
                    "head4": data.hex(),
                    "error": suspect,
                }
            )
            return base
    except Exception as exc:
        base.update(
            {
                "probe_status": "probe_error",
                "http_status": str(getattr(exc, "code", "") or ""),
                "error": repr(exc)[:300],
            }
        )
        return base


def probe_urls(entries: List[Dict[str, Any]], workers: int, timeout: float) -> List[Dict[str, Any]]:
    planned = [e for e in entries if e.get("kind") == "paper" and e.get("status") == "planned"]
    out: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_probe_one, row, timeout): row for row in planned}
        for fut in as_completed(futures):
            out.append(fut.result())
    return sorted(out, key=lambda r: (r.get("source", ""), r.get("doi", ""), r.get("title", "")))


def recheck_institutional(
    tsv_path: Path | None,
    entries: List[Dict[str, Any]],
    institutional_access: str,
) -> List[Dict[str, Any]]:
    if not tsv_path or not tsv_path.exists():
        return []
    with tsv_path.open(encoding="utf-8", newline="") as fh:
        old_rows = list(csv.DictReader(fh, delimiter="\t"))

    by_doi = {(e.get("doi") or "").lower(): e for e in entries if e.get("doi")}
    rows: List[Dict[str, Any]] = []
    for old in old_rows:
        doi = (old.get("doi") or "").lower()
        entry = by_doi.get(doi)
        old_action = old.get("recommended_action") or ""
        if entry is None:
            if doi and old_action == "institutional_access_candidate":
                new_status = f"{_institutional_status(institutional_access, old_action)}_manifest_missing"
            else:
                new_status = "manual_review_missing_doi_or_manifest"
            resolution = ""
            planned_url = ""
        elif entry.get("status") == "planned":
            new_status = "oa_candidate_after_unpaywall"
            resolution = entry.get("resolution") or ""
            planned_url = entry.get("planned_url") or ""
        elif entry.get("status") in {"paywalled", "no-url"}:
            new_status = _institutional_status(institutional_access, old_action)
            resolution = entry.get("resolution") or ""
            planned_url = ""
        else:
            new_status = entry.get("status") or "manual_review"
            resolution = entry.get("resolution") or ""
            planned_url = entry.get("planned_url") or ""
        rows.append(
            {
                "idx": old.get("idx") or "",
                "doi": old.get("doi") or "",
                "title": old.get("title") or "",
                "old_status": old.get("status") or "",
                "old_recommended_action": old_action,
                "new_status": new_status,
                "institutional_access": institutional_access,
                "resolver_status": (entry or {}).get("status", ""),
                "resolution": resolution,
                "planned_url": planned_url,
            }
        )
    return rows


def write_summary(
    path: Path,
    *,
    project: str,
    bundle: Path,
    zotero_root: Path,
    local_rows: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    probe_rows: List[Dict[str, Any]],
    inst_rows: List[Dict[str, Any]],
    flattened: int,
    institutional_access: str,
) -> None:
    entries = manifest.get("entries") or []
    status = Counter(e.get("status", "unknown") for e in entries)
    resolution = Counter(e.get("resolution", "unknown") for e in entries)
    local_conf = Counter(r.get("match_confidence", "") for r in local_rows)
    probe = Counter(r.get("probe_status", "") for r in probe_rows)
    inst = Counter(r.get("new_status", "") for r in inst_rows)

    title = f"{project} " if project else ""
    lines = [
        f"# {title}SHawn-bio-search ecosystem recheck",
        "",
        f"- project: `{project or ''}`",
        f"- bundle: `{bundle}`",
        f"- zotero_root: `{zotero_root}`",
        f"- candidate papers: {len(local_rows)}",
        f"- local strong matches: {local_conf.get('strong', 0)}",
        f"- local title-fuzzy candidates: {local_conf.get('candidate_review', 0)}",
        f"- local unmatched: {local_conf.get('none', 0)}",
        f"- manifest entries: {len(entries)}",
        f"- manifest status: {dict(status)}",
        f"- manifest resolution: {dict(resolution)}",
        f"- flattened paper dest paths: {flattened}",
        f"- institutional_access: `{institutional_access}`",
    ]
    if probe_rows:
        lines.append(f"- URL probe status: {dict(probe)}")
    else:
        lines.append("- URL probe status: skipped")
    if inst_rows:
        lines.append(f"- old institutional TSV recheck: {dict(inst)}")
    else:
        lines.append("- old institutional TSV recheck: skipped")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `planned` means an OA URL candidate exists; it is not proof that the URL is a valid article PDF unless `probe_status=pdf_head_ok`.",
            "- `institutional_access_ready` means the Linux authorized university/library browser route is available, but this wrapper still does not automate credentialed downloads.",
            "- `title_fuzzy` local matches are review candidates, not verified local holdings.",
            "- This wrapper does not download PDFs and does not use Sci-Hub, mirrors, proxy tricks, credential capture, or access-control evasion.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Recheck a SHawn-bio-search bundle against local/OA access layers")
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--project", default="")
    ap.add_argument("--zotero-root", type=Path, default=DEFAULT_ZOTERO_ROOT)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--institutional-tsv", type=Path, default=None)
    ap.add_argument(
        "--institutional-access",
        choices=INSTITUTIONAL_ACCESS_CHOICES,
        default="auto",
        help="Institutional route status for unresolved DOI/publisher records. auto resolves to available on Linux.",
    )
    ap.add_argument("--no-unpaywall", action="store_true")
    ap.add_argument("--skip-probe", action="store_true")
    ap.add_argument("--probe-workers", type=int, default=12)
    ap.add_argument("--probe-timeout", type=float, default=6.0)
    ap.add_argument("--keep-subdirs", action="store_true", help="Keep runner's default papers/ dest prefix")
    return ap


def main(argv: List[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    load_shawn_env()
    institutional_access = _resolve_institutional_access(args.institutional_access)
    out_dir = args.out_dir or _default_out_dir(args.bundle, args.project)
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = _load_bundle(args.bundle)
    local_rows = build_local_rows(bundle, args.zotero_root)
    _write_tsv(
        out_dir / "local_recheck.tsv",
        local_rows,
        [
            "idx", "title", "doi", "pmid", "pmcid", "source", "in_local_library",
            "match_type", "match_confidence", "local_pdf_path",
        ],
    )

    manifest = plan_from_bundle(
        args.bundle,
        args.zotero_root,
        kinds=["papers"],
        use_unpaywall=not args.no_unpaywall,
    )
    flattened = 0 if args.keep_subdirs else _flatten_paper_dest_paths(manifest)
    manifest_path = out_dir / ("manifest_no_unpaywall.json" if args.no_unpaywall else "manifest_unpaywall.json")
    save_manifest(manifest_path, manifest)

    entries = manifest.get("entries") or []
    probe_rows: List[Dict[str, Any]] = []
    if not args.skip_probe:
        probe_rows = probe_urls(entries, workers=args.probe_workers, timeout=args.probe_timeout)
        _write_tsv(
            out_dir / "url_probe.tsv",
            probe_rows,
            [
                "key", "source", "doi", "title", "resolution", "planned_url",
                "probe_status", "http_status", "content_type", "final_url", "head4", "error",
            ],
        )

    inst_rows = recheck_institutional(args.institutional_tsv, entries, institutional_access)
    if inst_rows:
        _write_tsv(
            out_dir / "institutional_recheck.tsv",
            inst_rows,
            [
                "idx", "doi", "title", "old_status", "old_recommended_action",
                "new_status", "institutional_access", "resolver_status", "resolution", "planned_url",
            ],
        )

    write_summary(
        out_dir / "SUMMARY.md",
        project=args.project,
        bundle=args.bundle,
        zotero_root=args.zotero_root,
        local_rows=local_rows,
        manifest=manifest,
        probe_rows=probe_rows,
        inst_rows=inst_rows,
        flattened=flattened,
        institutional_access=institutional_access,
    )

    print(f"saved: {out_dir / 'SUMMARY.md'}")
    print(f"saved: {out_dir / 'local_recheck.tsv'}")
    print(f"saved: {manifest_path}")
    if probe_rows:
        print(f"saved: {out_dir / 'url_probe.tsv'}")
    if inst_rows:
        print(f"saved: {out_dir / 'institutional_recheck.tsv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
