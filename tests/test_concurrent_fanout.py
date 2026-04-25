"""Tests for concurrent source fan-out in search_papers()."""

from __future__ import annotations

import threading
import time
from typing import List

import pytest

from shawn_bio_search import search as search_module
from shawn_bio_search.sources import _http


def _make_slow_fetcher(name: str, delay: float, marker: list):
    """Return a fake fetch_<source> that sleeps `delay` then returns one paper."""
    def _fetch(query: str, max_results: int):
        marker.append((name, time.monotonic()))
        time.sleep(delay)
        return [{
            "source": name,
            "id": f"{name}-1",
            "title": f"Result from {name}",
            "authors": [],
            "year": 2024,
            "doi": None,
            "url": "",
            "abstract": "",
        }]
    return _fetch


def _patch_all_fetchers(monkeypatch, names: List[str], delay: float, marker: list) -> None:
    """Replace every source fetcher referenced by search_module with a fake."""
    for name in names:
        attr = {
            "semantic_scholar": "fetch_semanticscholar",
        }.get(name, f"fetch_{name}")
        monkeypatch.setattr(search_module, attr, _make_slow_fetcher(name, delay, marker))


def test_fanout_finishes_in_parallel_wall_time(monkeypatch):
    """4 fetchers x 0.3s should complete in ~0.3s, not ~1.2s."""
    names = ["pubmed", "europe_pmc", "openalex", "crossref"]
    marker: list = []
    _patch_all_fetchers(monkeypatch, names, delay=0.3, marker=marker)
    monkeypatch.setenv("SBS_MAX_WORKERS", "8")

    t0 = time.monotonic()
    results = search_module.search_papers(query="x", max_results=5, sources=names)
    elapsed = time.monotonic() - t0

    assert len(results.papers) == len(names), "every source should contribute"
    assert elapsed < 0.9, f"parallel fan-out should beat sequential 1.2s; took {elapsed:.2f}s"


def test_fanout_isolates_failures(monkeypatch):
    """One failing source must not abort the others."""
    names = ["pubmed", "europe_pmc", "openalex"]
    marker: list = []
    _patch_all_fetchers(monkeypatch, names, delay=0.05, marker=marker)

    def _broken(query: str, max_results: int):
        raise RuntimeError("boom")
    monkeypatch.setattr(search_module, "fetch_europe_pmc", _broken)

    results = search_module.search_papers(query="x", max_results=5, sources=names)
    assert len(results.papers) == 2  # pubmed + openalex survived
    assert any("europe_pmc failed" in w for w in results.warnings)


def test_max_workers_env_var_caps_concurrency(monkeypatch):
    """SBS_MAX_WORKERS=1 forces sequential behavior — used to opt out."""
    names = ["pubmed", "europe_pmc", "openalex", "crossref"]
    marker: list = []
    _patch_all_fetchers(monkeypatch, names, delay=0.2, marker=marker)
    monkeypatch.setenv("SBS_MAX_WORKERS", "1")

    t0 = time.monotonic()
    search_module.search_papers(query="x", max_results=5, sources=names)
    elapsed = time.monotonic() - t0

    assert elapsed >= 0.7, (
        f"with SBS_MAX_WORKERS=1 fan-out should be sequential (>=0.8s); took {elapsed:.2f}s"
    )


def test_rate_limit_is_thread_safe(monkeypatch):
    """Concurrent _rate_limit calls for the same host must serialize."""
    monkeypatch.setitem(_http._HOST_MIN_INTERVAL, "concurrency.test", 0.05)
    _http._LAST_CALL_AT.pop("concurrency.test", None)

    timestamps: List[float] = []
    timestamps_lock = threading.Lock()

    def _hit():
        _http._rate_limit("concurrency.test")
        with timestamps_lock:
            timestamps.append(time.monotonic())

    threads = [threading.Thread(target=_hit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    timestamps.sort()
    # Each consecutive pair must be at least the rate-limit interval apart
    # (give a small tolerance for jitter).
    deltas = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    assert all(d >= 0.04 for d in deltas), (
        f"rate-limit serialization broke under threads; deltas={deltas}"
    )
