"""Browser-assisted institutional access queue handling.

This module opens DOI/publisher pages in the user's normal browser and records
an audit trail. It deliberately does not download PDFs, read browser cookies,
handle credentials, or bypass publisher access controls.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


REPO = Path(__file__).resolve().parents[1]
FALLBACK_QUEUE = REPO / "outputs/dhcr24_260427/DHCR24_INSTITUTIONAL_ACCESS_READY_260427.tsv"
DEFAULT_OUT_DIR = REPO / "outputs/institutional_access"
DEFAULT_BROWSER_COMMAND = "xdg-open"
DEFAULT_ACCESS_ROUTE = "current_network_institutional_access"
DEFAULT_STATUSES = ["institutional_access_ready"]
ACTIONABLE_STATUSES = [
    "institutional_access_ready",
    "manual_review_institutional_access_available",
]
ACCESS_CHOICES = ("auto", "available", "candidate", "unavailable")


@dataclass
class EnvironmentStatus:
    institutional_access: str
    access_route: str
    network_label: str
    auth_provider_label: str
    network_probe_status: str
    url_template: str
    browser_command: str
    browser_command_found: bool
    platform_name: str
    queue_path: Path
    queue_exists: bool


def _slug(value: str, fallback: str = "current_network") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-").lower()
    return value or fallback


def _looks_institutional_network(network_label: str) -> bool:
    text = network_label.lower()
    markers = [
        "university",
        "college",
        "hospital",
        "institute",
        "campus",
        "library",
        ".edu",
        "school",
        "research",
    ]
    return any(marker in text for marker in markers)


def detect_public_network(timeout: float = 2.5) -> Dict[str, str]:
    """Best-effort public network label for audit purposes."""
    try:
        req = urllib.request.Request(
            "https://ipinfo.io/json",
            headers={"User-Agent": "shawn-bio-search-institutional/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        label = data.get("org") or data.get("hostname") or data.get("ip") or ""
        return {
            "status": "ok",
            "label": str(label),
            "ip": str(data.get("ip") or ""),
        }
    except Exception as exc:
        return {
            "status": f"error:{type(exc).__name__}",
            "label": "",
            "ip": "",
        }


def resolve_network_label(value: str = "", *, detect_network: bool = False) -> Dict[str, str]:
    explicit = value or os.environ.get("SHAWN_INSTITUTIONAL_NETWORK_LABEL", "").strip()
    if explicit:
        return {"status": "explicit", "label": explicit, "ip": ""}
    if detect_network or os.environ.get("SHAWN_INSTITUTIONAL_DETECT_NETWORK", "").strip() == "1":
        return detect_public_network()
    return {"status": "not_requested", "label": "", "ip": ""}


def resolve_auth_provider_label(value: str = "") -> str:
    return (
        value
        or os.environ.get("SHAWN_INSTITUTIONAL_AUTH_PROVIDER_LABEL", "").strip()
        or os.environ.get("SHAWN_INSTITUTIONAL_ACCESS_PROVIDER_LABEL", "").strip()
    )


def resolve_url_template(value: str = "") -> str:
    return value or os.environ.get("SHAWN_INSTITUTIONAL_URL_TEMPLATE", "").strip()


def resolve_access_route(value: str = "", network_label: str = "", auth_provider_label: str = "") -> str:
    explicit = value or os.environ.get("SHAWN_INSTITUTIONAL_ROUTE_LABEL", "").strip()
    if explicit:
        return _slug(explicit, DEFAULT_ACCESS_ROUTE)
    if auth_provider_label:
        return f"institutional_access_{_slug(auth_provider_label)}"
    if network_label:
        return f"institutional_access_{_slug(network_label)}"
    return DEFAULT_ACCESS_ROUTE


def resolve_institutional_access(
    value: str = "auto",
    network_label: str = "",
    auth_provider_label: str = "",
) -> str:
    """Resolve institutional access mode in a portable way."""
    if value != "auto":
        return value

    env_value = os.environ.get("SHAWN_INSTITUTIONAL_ACCESS", "").strip().lower()
    if env_value in {"available", "candidate", "unavailable"}:
        return env_value

    if _looks_institutional_network(auth_provider_label) or _looks_institutional_network(network_label):
        return "available"
    return "candidate"


def default_queue_path() -> Path:
    explicit = os.environ.get("SHAWN_INSTITUTIONAL_QUEUE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    candidates = sorted(
        REPO.glob("outputs/**/*INSTITUTIONAL_ACCESS_READY*.tsv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else FALLBACK_QUEUE


def default_out_dir() -> Path:
    explicit = os.environ.get("SHAWN_INSTITUTIONAL_OUT_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return DEFAULT_OUT_DIR


def resolve_browser_command(value: str = "") -> str:
    return value or os.environ.get("SHAWN_INSTITUTIONAL_BROWSER", "").strip() or DEFAULT_BROWSER_COMMAND


def environment_status(
    *,
    access: str = "auto",
    queue: Optional[Path] = None,
    browser_command: str = "",
    network_label: str = "",
    auth_provider_label: str = "",
    route_label: str = "",
    url_template: str = "",
    detect_network: bool = False,
) -> EnvironmentStatus:
    command = resolve_browser_command(browser_command)
    queue_path = queue or default_queue_path()
    network = resolve_network_label(network_label, detect_network=detect_network)
    label = network.get("label", "")
    provider = resolve_auth_provider_label(auth_provider_label)
    return EnvironmentStatus(
        institutional_access=resolve_institutional_access(access, label, provider),
        access_route=resolve_access_route(route_label, label, provider),
        network_label=label,
        auth_provider_label=provider,
        network_probe_status=network.get("status", ""),
        url_template=resolve_url_template(url_template),
        browser_command=command,
        browser_command_found=shutil.which(command) is not None,
        platform_name=platform.system().lower(),
        queue_path=queue_path,
        queue_exists=queue_path.exists(),
    )


def load_queue(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path: Path, rows: Iterable[Dict[str, str]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def doi_url(doi: str) -> str:
    doi = doi.strip()
    if doi.startswith("http://") or doi.startswith("https://"):
        return doi
    return f"https://doi.org/{doi}"


def access_url(doi: str, url_template: str = "") -> str:
    base = doi_url(doi)
    if not url_template:
        return base
    raw_doi = doi.strip()
    return (
        url_template
        .replace("{url}", urllib.parse.quote(base, safe=""))
        .replace("{raw_url}", base)
        .replace("{doi}", urllib.parse.quote(raw_doi, safe=""))
        .replace("{raw_doi}", raw_doi)
    )


def selected_statuses(statuses: Optional[List[str]], all_actionable: bool) -> List[str]:
    if all_actionable:
        return ACTIONABLE_STATUSES
    return statuses or DEFAULT_STATUSES


def select_rows(
    rows: List[Dict[str, str]],
    *,
    statuses: List[str],
    start: int = 0,
    limit: Optional[int] = 10,
) -> List[Dict[str, str]]:
    selected = [
        r
        for r in rows
        if (r.get("new_status") or r.get("status") or "") in statuses and r.get("doi")
    ]
    selected = selected[max(0, start):]
    if limit is not None:
        selected = selected[:max(0, limit)]
    return selected


def open_queue_rows(
    rows: List[Dict[str, str]],
    *,
    browser_command: str,
    access_route: str,
    network_label: str,
    auth_provider_label: str,
    url_template: str,
    preserve_queue_route: bool,
    batch_size: int,
    sleep_s: float,
    dry_run: bool,
) -> List[Dict[str, str]]:
    audit_rows: List[Dict[str, str]] = []
    for i, row in enumerate(rows, 1):
        source_url = doi_url(row.get("doi", ""))
        url = access_url(row.get("doi", ""), url_template)
        action = "dry_run"
        error = ""
        if not dry_run:
            try:
                subprocess.Popen(
                    [browser_command, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                action = "open_requested"
            except Exception as exc:  # pragma: no cover - platform-specific failure text
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
                "access_route": (row.get("access_route") or access_route) if preserve_queue_route else access_route,
                "network_label": network_label,
                "auth_provider_label": auth_provider_label,
                "source_url": source_url,
                "url": url,
                "error": error,
            }
        )
        if i % max(1, batch_size) == 0 and i < len(rows):
            time.sleep(max(0.0, sleep_s))
    return audit_rows


def audit_fieldnames() -> List[str]:
    return [
        "timestamp",
        "action",
        "idx",
        "doi",
        "title",
        "new_status",
        "institutional_access",
        "access_route",
        "network_label",
        "auth_provider_label",
        "source_url",
        "url",
        "error",
    ]


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="shawn-bio-institutional",
        description="Open institutional-access DOI queues in a normal browser and write an audit TSV.",
    )
    ap.add_argument("--queue", type=Path, default=default_queue_path())
    ap.add_argument("--out-dir", type=Path, default=default_out_dir())
    ap.add_argument("--status", action="append", default=None, help="Queue status to open; repeatable")
    ap.add_argument("--all-actionable", action="store_true", help="Open ready and manual-review institutional records")
    ap.add_argument("--start", type=int, default=0, help="Offset within selected queue rows")
    ap.add_argument("--limit", type=int, default=10, help="Max rows to open; use 0 for all selected rows")
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=2.0, help="Seconds between batches")
    ap.add_argument("--browser-command", default="", help="Default: SHAWN_INSTITUTIONAL_BROWSER or xdg-open")
    ap.add_argument("--institutional-access", choices=ACCESS_CHOICES, default="auto")
    ap.add_argument("--network-label", default="", help="Current network/institution label for audit route")
    ap.add_argument("--auth-provider-label", default="", help="Authenticated library/provider label for audit route")
    ap.add_argument("--route-label", default="", help="Override audit access_route label")
    ap.add_argument(
        "--url-template",
        default="",
        help="Official library/proxy URL template. Supports {url}, {raw_url}, {doi}, {raw_doi}.",
    )
    ap.add_argument(
        "--detect-network",
        dest="detect_network",
        action="store_true",
        default=True,
        help="Best-effort public IP org detection for audit (default)",
    )
    ap.add_argument(
        "--no-detect-network",
        dest="detect_network",
        action="store_false",
        help="Disable public IP org detection",
    )
    ap.add_argument("--preserve-queue-route", action="store_true", help="Keep access_route already present in queue rows")
    ap.add_argument("--check-env", action="store_true", help="Print resolved institutional/browser environment and exit")
    ap.add_argument("--dry-run", action="store_true")
    return ap


def print_environment(status: EnvironmentStatus) -> None:
    print(f"institutional_access={status.institutional_access}")
    print(f"access_route={status.access_route}")
    print(f"network_label={status.network_label}")
    print(f"auth_provider_label={status.auth_provider_label}")
    print(f"network_probe_status={status.network_probe_status}")
    print(f"url_template_set={str(bool(status.url_template)).lower()}")
    print(f"platform={status.platform_name}")
    print(f"browser_command={status.browser_command}")
    print(f"browser_command_found={str(status.browser_command_found).lower()}")
    print(f"queue={status.queue_path}")
    print(f"queue_exists={str(status.queue_exists).lower()}")


def main_cli(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    env = environment_status(
        access=args.institutional_access,
        queue=args.queue,
        browser_command=args.browser_command,
        network_label=args.network_label,
        auth_provider_label=args.auth_provider_label,
        route_label=args.route_label,
        url_template=args.url_template,
        detect_network=args.detect_network,
    )
    if args.check_env:
        print_environment(env)
        return 0 if env.browser_command_found else 2

    if env.institutional_access == "unavailable":
        print("ERROR: institutional access is unavailable in this environment.", file=sys.stderr)
        return 2
    if not env.browser_command_found:
        print(f"ERROR: browser command not found: {env.browser_command}", file=sys.stderr)
        return 2
    if not env.queue_exists:
        print(f"ERROR: queue does not exist: {env.queue_path}", file=sys.stderr)
        return 2

    statuses = selected_statuses(args.status, args.all_actionable)
    limit = None if args.limit == 0 else args.limit
    selected = select_rows(load_queue(env.queue_path), statuses=statuses, start=args.start, limit=limit)

    audit_rows = open_queue_rows(
        selected,
        browser_command=env.browser_command,
        access_route=env.access_route,
        network_label=env.network_label,
        auth_provider_label=env.auth_provider_label,
        url_template=env.url_template,
        preserve_queue_route=args.preserve_queue_route,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        dry_run=args.dry_run,
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = args.out_dir / f"institutional_browser_open_audit_{stamp}.tsv"
    write_tsv(audit_path, audit_rows, audit_fieldnames())

    print(f"institutional_access={env.institutional_access}")
    print(f"access_route={env.access_route}")
    if env.network_label:
        print(f"network_label={env.network_label}")
    if env.auth_provider_label:
        print(f"auth_provider_label={env.auth_provider_label}")
    print(f"selected={len(selected)}")
    print(f"saved={audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
