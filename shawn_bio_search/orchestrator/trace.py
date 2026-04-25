"""Trace event bus for capability/source provenance.

Four channels run simultaneously, each independently toggleable:

1. **stderr live**: one line per event, color-coded by status. Disabled when
   ``SBS_TRACE_VERBOSE`` env var is unset or ``"0"``.
2. **per-run collector**: a callable registered via :func:`set_run_collector`
   captures every event during a single CLI/script run. Used by
   ``scripts/search_bundle.py`` to render a markdown trace section into
   ``SEARCH_LOG.md``.
3. **persistent JSONL**: every event is appended to
   ``~/.cache/shawn-bio-search/trace.jsonl``. Disabled when
   ``SBS_TRACE_PERSIST=0``. TTL-pruned by :func:`prune_persistent_trace`.
4. **degradation report**: not handled here; the degradation module reads
   the in-memory or persistent stream and renders ``DEGRADATION_REPORT.md``.

The runner (PR B) emits events; PR A only provides the bus.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, List, Optional

TraceCollector = Callable[["TraceEvent"], None]


SUCCESS_STATUSES = frozenset({"success", "cache_hit"})

ALL_STATUSES = frozenset(
    {
        "success",
        "cache_hit",
        "empty",
        "missing_key",
        "http_4xx",
        "http_5xx",
        "timeout",
        "throttled",
        "exception",
        "skipped",
    }
)


@dataclass
class TraceEvent:
    """One step of a capability execution."""

    timestamp: float
    capability: str
    source: str
    chain_position: int
    status: str
    latency_ms: int = 0
    result_count: int = 0
    cache_hit: bool = False
    query_summary: str = ""
    http_status: Optional[int] = None
    retry_after_s: Optional[float] = None
    error_kind: Optional[str] = None
    why: str = ""
    extra: dict = field(default_factory=dict)

    def to_jsonable(self) -> dict:
        d = asdict(self)
        # ``extra`` may contain non-serializable values; coerce to repr.
        if d.get("extra"):
            safe_extra = {}
            for k, v in d["extra"].items():
                try:
                    json.dumps(v)
                    safe_extra[k] = v
                except (TypeError, ValueError):
                    safe_extra[k] = repr(v)
            d["extra"] = safe_extra
        return d

    @classmethod
    def from_dict(cls, payload: dict) -> "TraceEvent":
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in payload.items() if k in known}
        data.setdefault("extra", {})
        return cls(**data)

    @property
    def is_success(self) -> bool:
        return self.status in SUCCESS_STATUSES

    @property
    def is_failure(self) -> bool:
        return self.status not in SUCCESS_STATUSES and self.status != "skipped"


# ---------------------------------------------------------------------------
# Channel state (module-level; thread-safe writes)
# ---------------------------------------------------------------------------

_RUN_COLLECTOR: Optional[TraceCollector] = None
_LOCK = threading.Lock()

DEFAULT_TRACE_PATH = (
    Path(os.environ.get("SBS_TRACE_PATH", ""))
    if os.environ.get("SBS_TRACE_PATH")
    else Path.home() / ".cache" / "shawn-bio-search" / "trace.jsonl"
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "", "false", "no", "off"}


def _stderr_enabled() -> bool:
    return _bool_env("SBS_TRACE_VERBOSE", default=False)


def _persist_enabled() -> bool:
    return _bool_env("SBS_TRACE_PERSIST", default=True)


def set_run_collector(collector: Optional[TraceCollector]) -> None:
    """Register a callable to receive every emitted event for the current run.

    Pass ``None`` to clear. Replacing an existing collector is allowed; the
    previous one is silently dropped.
    """
    global _RUN_COLLECTOR
    with _LOCK:
        _RUN_COLLECTOR = collector


def clear_run_collector() -> None:
    set_run_collector(None)


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

_STATUS_GLYPH = {
    "success": "✓",
    "cache_hit": "◎",
    "empty": "·",
    "missing_key": "✗",
    "http_4xx": "✗",
    "http_5xx": "⚠",
    "timeout": "⏱",
    "throttled": "⧖",
    "exception": "☠",
    "skipped": "→",
}


def _format_stderr(ev: TraceEvent) -> str:
    glyph = _STATUS_GLYPH.get(ev.status, "?")
    parts = [
        f"[trace] {glyph} {ev.capability} step={ev.chain_position}",
        f"src={ev.source}",
        f"status={ev.status}",
    ]
    if ev.latency_ms:
        parts.append(f"{ev.latency_ms}ms")
    if ev.result_count:
        parts.append(f"n={ev.result_count}")
    if ev.http_status is not None:
        parts.append(f"http={ev.http_status}")
    if ev.error_kind:
        parts.append(f"err={ev.error_kind}")
    if ev.why:
        parts.append(f"- {ev.why}")
    return " ".join(parts)


def _append_jsonl(ev: TraceEvent, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev.to_jsonable(), ensure_ascii=False))
            fh.write("\n")
    except OSError:
        # Persistence is best-effort; never crash the search because of trace IO.
        pass


def emit(ev: TraceEvent) -> None:
    """Send an event to all enabled channels."""
    with _LOCK:
        collector = _RUN_COLLECTOR

    if collector is not None:
        try:
            collector(ev)
        except Exception:  # collector errors must never propagate
            pass

    if _stderr_enabled():
        try:
            sys.stderr.write(_format_stderr(ev) + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    if _persist_enabled():
        _append_jsonl(ev, DEFAULT_TRACE_PATH)


# ---------------------------------------------------------------------------
# Convenience constructor
# ---------------------------------------------------------------------------


def make_event(
    capability: str,
    source: str,
    chain_position: int,
    status: str,
    *,
    started_at: Optional[float] = None,
    latency_ms: Optional[int] = None,
    result_count: int = 0,
    cache_hit: bool = False,
    query_summary: str = "",
    http_status: Optional[int] = None,
    retry_after_s: Optional[float] = None,
    error_kind: Optional[str] = None,
    why: str = "",
    extra: Optional[dict] = None,
) -> TraceEvent:
    """Build a TraceEvent with sensible defaults.

    If ``started_at`` is provided, ``latency_ms`` is derived from
    ``time.monotonic()`` deltas. Otherwise the caller is responsible for
    passing ``latency_ms`` directly (or leaving it at zero).
    """
    if status not in ALL_STATUSES:
        # Not raising; trace must be tolerant. Tag with a marker so we can spot
        # typos in registry code.
        why = (why + f" [unknown_status={status}]").strip()
    if latency_ms is None and started_at is not None:
        latency_ms = int((time.monotonic() - started_at) * 1000)
    return TraceEvent(
        timestamp=time.time(),
        capability=capability,
        source=source,
        chain_position=chain_position,
        status=status,
        latency_ms=latency_ms or 0,
        result_count=result_count,
        cache_hit=cache_hit,
        query_summary=query_summary[:200],
        http_status=http_status,
        retry_after_s=retry_after_s,
        error_kind=error_kind,
        why=why,
        extra=dict(extra) if extra else {},
    )


# ---------------------------------------------------------------------------
# Persistent trace iteration & TTL pruning
# ---------------------------------------------------------------------------


def iter_persistent_trace(
    path: Optional[Path] = None,
    last_n: Optional[int] = None,
) -> Iterator[TraceEvent]:
    """Yield TraceEvents from the persistent JSONL store.

    If ``last_n`` is given, only the final N events are returned (still in
    chronological order). Missing or unreadable file yields nothing.
    """
    target = Path(path) if path else DEFAULT_TRACE_PATH
    if not target.exists():
        return
    try:
        with target.open("r", encoding="utf-8") as fh:
            lines: List[str] = fh.readlines()
    except OSError:
        return
    if last_n is not None and last_n > 0:
        lines = lines[-last_n:]
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield TraceEvent.from_dict(json.loads(raw))
        except (TypeError, ValueError):
            continue


def prune_persistent_trace(
    retention_days: Optional[int] = None,
    path: Optional[Path] = None,
) -> int:
    """Drop events older than ``retention_days`` from the persistent store.

    Defaults to ``SBS_TRACE_RETENTION_DAYS`` env var, or 90 days. Returns
    the number of events kept after pruning. Missing file is a no-op (returns 0).
    """
    if retention_days is None:
        try:
            retention_days = int(os.environ.get("SBS_TRACE_RETENTION_DAYS", "90"))
        except ValueError:
            retention_days = 90
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400.0
    target = Path(path) if path else DEFAULT_TRACE_PATH
    if not target.exists():
        return 0
    kept: List[str] = []
    try:
        with target.open("r", encoding="utf-8") as fh:
            for raw in fh:
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except ValueError:
                    continue
                ts = payload.get("timestamp")
                if isinstance(ts, (int, float)) and ts >= cutoff:
                    kept.append(stripped)
    except OSError:
        return 0
    try:
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        return len(kept)
    return len(kept)


# ---------------------------------------------------------------------------
# Light helpers for tests / introspection
# ---------------------------------------------------------------------------


def collect_into(buffer: List[TraceEvent]) -> TraceCollector:
    """Build a collector that appends events to ``buffer``."""

    def _collector(ev: TraceEvent) -> None:
        buffer.append(ev)

    return _collector


def filter_failures(events: Iterable[TraceEvent]) -> List[TraceEvent]:
    return [ev for ev in events if ev.is_failure]
