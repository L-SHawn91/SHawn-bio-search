"""Optional .env loader.

Loads API keys from a `.env` file in the current working directory or any
parent directory without introducing a dependency. If `python-dotenv` is
installed it's used for robustness; otherwise a minimal parser handles the
common `KEY=value` and `KEY="value"` forms.

Call `load_dotenv()` manually once at program start. We do NOT auto-load on
import to avoid surprise side-effects in library callers.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


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


def load_dotenv(path: Optional[str | Path] = None, override: bool = False) -> Optional[Path]:
    """Populate `os.environ` from a .env file.

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

    values = _parse_minimal(resolved)
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return resolved
