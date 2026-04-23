"""Optional .env loader + SHawn ecosystem secrets bootstrap.

Loads API keys from:

    1. `.env` in cwd or any parent directory (project-local override)
    2. `~/.shawn/secrets/api_keys.env`      (SHawn ecosystem local default)
    3. `~/.openclaw/openclaw-sync/.secrets/api_keys.env`   (legacy OpenClaw bridge)
    4. `~/.openclaw/workspace/.secrets/api_keys.env`        (legacy OpenClaw bridge)
    5. `~/.openclaw/workspace/.secrets/shared/api_keys.env` (legacy OpenClaw bridge)

Earlier paths win. `~/.shawn/secrets/api_keys.env` is the canonical local default —
the OpenClaw locations are fallbacks kept only for backward compatibility.

If `python-dotenv` is installed it's used for robustness; otherwise a minimal parser
handles `KEY=value` and `KEY="value"`.

Call `load_dotenv()` or `load_shawn_env()` manually once at program start. We do
NOT auto-load on import to avoid surprise side-effects in library callers.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional


_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


# =============================================================================
# SHawn ecosystem canonical secret paths — local default first, OpenClaw legacy last
# =============================================================================

SHAWN_LOCAL_DEFAULT = Path.home() / ".shawn" / "secrets" / "api_keys.env"

_OPENCLAW_LEGACY = [
    Path.home() / ".openclaw" / "openclaw-sync" / ".secrets" / "api_keys.env",
    Path.home() / ".openclaw" / "workspace" / ".secrets" / "api_keys.env",
    Path.home() / ".openclaw" / "workspace" / ".secrets" / "shared" / "api_keys.env",
]


def _find_dotenv(start: Optional[Path] = None) -> Optional[Path]:
    cur = (start or Path.cwd()).resolve()
    for directory in [cur, *cur.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def _parse_minimal(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        # Strip surrounding quotes if balanced.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def _apply(values: dict[str, str], override: bool) -> None:
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value


def load_dotenv(path: Optional[str | Path] = None, override: bool = False) -> Optional[Path]:
    """Populate `os.environ` from a single .env file.

    Args:
        path: Explicit .env path. If None, searches upward from CWD.
        override: If True, values in the file replace existing env vars.

    Returns:
        The path loaded, or None if no file was found.
    """
    resolved = Path(path) if path else _find_dotenv()
    if resolved is None or not resolved.is_file():
        return None

    # Prefer python-dotenv when available for edge-case compatibility.
    try:
        from dotenv import load_dotenv as _lib_load_dotenv
        _lib_load_dotenv(str(resolved), override=override)
        return resolved
    except ImportError:
        pass

    _apply(_parse_minimal(resolved), override)
    return resolved


def load_shawn_env(override: bool = False, skip_legacy: bool = False) -> List[Path]:
    """Load SHawn ecosystem secrets from every known canonical location.

    Precedence (earlier wins when `override=False`):

        1. `.env` in CWD or any parent
        2. `~/.shawn/secrets/api_keys.env`    (SHawn local default — canonical)
        3. OpenClaw legacy paths (if `skip_legacy=False`)

    When a library caller just needs "load any SHawn API keys this machine has",
    this is the one-shot entrypoint. Returns the list of files actually applied,
    in the order they were processed.
    """
    loaded: List[Path] = []

    candidates: List[Path] = []
    dotenv = _find_dotenv()
    if dotenv:
        candidates.append(dotenv)
    candidates.append(SHAWN_LOCAL_DEFAULT)
    if not skip_legacy:
        candidates.extend(_OPENCLAW_LEGACY)

    for path in candidates:
        if not path.is_file():
            continue
        _apply(_parse_minimal(path), override)
        loaded.append(path)
    return loaded
