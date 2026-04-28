#!/usr/bin/env python3
"""Compatibility wrapper for shawn-bio-institutional."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from shawn_bio_search.institutional_access import main_cli  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main_cli())
