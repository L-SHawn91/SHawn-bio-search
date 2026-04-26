"""Shared HTTP helper: timeout, retry, rate-limiting, proper TLS verification.

Use `http_json` / `http_text` from new source modules to avoid duplicating
urllib boilerplate. Existing modules may migrate over time.
"""

from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

USER_AGENT = "shawn-bio-search/0.1 (+https://github.com/l-shawn91/shawn-bio-search)"
DEFAULT_TIMEOUT = 30

# Per-host minimum seconds between calls; enforced lazily.
_HOST_MIN_INTERVAL: Dict[str, float] = {
    "api.semanticscholar.org": 1.1,
    "eutils.ncbi.nlm.nih.gov": 0.35,
    "api.biorxiv.org": 1.1,
    "api.medrxiv.org": 1.1,
    "api.crossref.org": 0.2,
    "api.openalex.org": 0.2,
    "www.ebi.ac.uk": 0.2,
    "api.unpaywall.org": 0.15,
    "api.openaire.eu": 0.2,
    "api.core.ac.uk": 0.5,
    "export.arxiv.org": 3.0,  # arXiv asks >3s between calls
    "zenodo.org": 0.5,
    "api.figshare.com": 0.3,
    "api.datacite.org": 0.3,
    "www.biorxiv.org": 1.1,
    "www.medrxiv.org": 1.1,
    "europepmc.org": 0.5,
    "ftp.ncbi.nlm.nih.gov": 0.5,
    "datadryad.org": 0.5,
    "api.cellxgene.cziscience.com": 0.3,
}
_LAST_CALL_AT: Dict[str, float] = {}
_HOST_LOCKS: Dict[str, threading.Lock] = {}
_HOST_LOCKS_LOCK = threading.Lock()


def _host_lock(host: str) -> threading.Lock:
    lock = _HOST_LOCKS.get(host)
    if lock is not None:
        return lock
    with _HOST_LOCKS_LOCK:
        lock = _HOST_LOCKS.get(host)
        if lock is None:
            lock = threading.Lock()
            _HOST_LOCKS[host] = lock
        return lock


def _rate_limit(host: str) -> None:
    min_interval = _HOST_MIN_INTERVAL.get(host, 0.0)
    if min_interval <= 0:
        return
    with _host_lock(host):
        last = _LAST_CALL_AT.get(host, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _LAST_CALL_AT[host] = time.monotonic()


def _open(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    data: Optional[bytes] = None,
    method: Optional[str] = None,
    max_retries: int = 3,
) -> bytes:
    """Open a URL with retries, rate limiting, and proper TLS verification."""
    host = urllib.parse.urlparse(url).hostname or ""
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    ctx = ssl.create_default_context()  # verifies certs by default
    last_exc: Optional[BaseException] = None

    for attempt in range(max_retries + 1):
        _rate_limit(host)
        try:
            req = urllib.request.Request(url, data=data, headers=merged_headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 2.0 * (2 ** attempt)
                except (TypeError, ValueError):
                    delay = 2.0 * (2 ** attempt)
                time.sleep(min(delay, 30.0))
                continue
            if 500 <= exc.code < 600 and attempt < max_retries:
                time.sleep(2.0 * (2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError(f"request failed without exception: {url}")


def http_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    data: Optional[bytes] = None,
    method: Optional[str] = None,
    max_retries: int = 3,
) -> Any:
    raw = _open(url, headers=headers, timeout=timeout, data=data, method=method, max_retries=max_retries)
    return json.loads(raw.decode("utf-8"))


def http_text(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = 3,
) -> str:
    raw = _open(url, headers=headers, timeout=timeout, max_retries=max_retries)
    return raw.decode("utf-8", "ignore")


def build_url(base: str, params: Dict[str, Any]) -> str:
    cleaned = {k: v for k, v in params.items() if v is not None and v != ""}
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(cleaned, doseq=True)
