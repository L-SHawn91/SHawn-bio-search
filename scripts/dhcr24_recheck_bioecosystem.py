#!/usr/bin/env python3
"""DHCR24 preset for the general SHawn-bio-search ecosystem recheck wrapper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from recheck_bioecosystem import main as recheck_main  # noqa: E402


DEFAULTS = {
    "--project": "DHCR24",
    "--bundle": str(REPO / "outputs/dhcr24_260427/dhcr24_combined_189_search_bundle_for_download_260427.json"),
    "--out-dir": str(REPO / "outputs/dhcr24_260427/recheck_bioecosystem_260427"),
    "--institutional-tsv": str(REPO / "outputs/dhcr24_260427/dhcr24_institutional_access_candidates_260427.tsv"),
    "--institutional-access": "available",
}


def _has_option(argv: List[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(flag + "=") for arg in argv)


def main(argv: List[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        return recheck_main(args)
    prefix: List[str] = []
    for flag, value in DEFAULTS.items():
        if not _has_option(args, flag):
            prefix.extend([flag, value])
    return recheck_main(prefix + args)


if __name__ == "__main__":
    raise SystemExit(main())
