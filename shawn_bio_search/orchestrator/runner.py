"""Capability runner: walk a fallback chain, emit trace events, return data.

The runner is intentionally minimal:

- Sequentially calls each :class:`SourceStep` in the chain.
- Skips a step (with a ``missing_key`` event) when its source needs an env
  var that is not configured.
- Catches HTTP / timeout / generic exceptions and maps them to trace
  statuses (``http_4xx``, ``http_5xx``, ``throttled``, ``timeout``,
  ``exception``).
- Stops at the first step whose result satisfies the capability's
  ``success_predicate``.
- Always returns a :class:`CapabilityResult` — never raises.
"""

from __future__ import annotations

import time
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from . import capabilities as _caps
from .trace import TraceEvent, emit, make_event


@dataclass
class CapabilityResult:
    capability: str
    data: List[Dict[str, Any]]
    used_source: Optional[str]
    trace: List[TraceEvent] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.used_source is not None


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


def _classify_exception(exc: BaseException) -> Dict[str, Any]:
    """Translate a fetcher exception into trace fields."""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 429:
            return {"status": "throttled", "http_status": code}
        if 400 <= code < 500:
            return {"status": "http_4xx", "http_status": code}
        if 500 <= code < 600:
            return {"status": "http_5xx", "http_status": code}
        return {"status": "exception", "http_status": code}
    if isinstance(exc, TimeoutError):
        return {"status": "timeout"}
    if isinstance(exc, urllib.error.URLError):
        # URLError wraps timeouts and connection issues; surface as timeout if
        # the cause looks like one, otherwise as exception.
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return {"status": "timeout"}
        if reason is not None and "timed out" in str(reason).lower():
            return {"status": "timeout"}
        return {"status": "exception"}
    return {"status": "exception"}


def _summarize_args(args: Mapping[str, Any]) -> str:
    """Build a one-line, truncated representation of the capability args."""
    if not args:
        return ""
    parts: List[str] = []
    for key in ("query", "doi", "pmid", "first_author", "year"):
        val = args.get(key)
        if val:
            parts.append(f"{key}={val}")
    if not parts:
        # Fall back to the first two keys, whatever they are.
        for key, val in list(args.items())[:2]:
            parts.append(f"{key}={val}")
    summary = ", ".join(parts)
    return summary[:200]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_capability(name: str, **args: Any) -> CapabilityResult:
    """Execute the named capability and return the first sufficient result.

    All trace events are emitted via :func:`shawn_bio_search.orchestrator.trace.emit`.
    The returned ``trace`` list is the same set of events in chronological order.
    """
    cap = _caps.get(name)
    query_summary = _summarize_args(args)
    events: List[TraceEvent] = []

    for step_idx, step in enumerate(cap.chain):
        # 1) Missing-key short circuit
        missing = _caps.missing_required_keys(step.source)
        if missing:
            ev = make_event(
                capability=cap.name,
                source=step.source,
                chain_position=step_idx,
                status="missing_key",
                latency_ms=0,
                why=f"needs env: {', '.join(missing)}",
                query_summary=query_summary,
                extra={"missing_env": list(missing)},
            )
            events.append(ev)
            emit(ev)
            continue

        # 2) Invoke the fetcher with timing
        started = time.monotonic()
        try:
            records = list(step.fetcher(args))
            latency_ms = int((time.monotonic() - started) * 1000)
        except BaseException as exc:  # noqa: BLE001 — we classify and continue
            latency_ms = int((time.monotonic() - started) * 1000)
            classified = _classify_exception(exc)
            ev = make_event(
                capability=cap.name,
                source=step.source,
                chain_position=step_idx,
                status=classified["status"],
                latency_ms=latency_ms,
                http_status=classified.get("http_status"),
                error_kind=type(exc).__name__,
                why=str(exc)[:160] or step.why,
                query_summary=query_summary,
            )
            events.append(ev)
            emit(ev)
            continue

        # 3) Empty vs success
        if not records:
            ev = make_event(
                capability=cap.name,
                source=step.source,
                chain_position=step_idx,
                status="empty",
                latency_ms=latency_ms,
                why=step.why,
                query_summary=query_summary,
            )
            events.append(ev)
            emit(ev)
            continue

        if cap.success_predicate(records, args):
            ev = make_event(
                capability=cap.name,
                source=step.source,
                chain_position=step_idx,
                status="success",
                latency_ms=latency_ms,
                result_count=len(records),
                why=step.why,
                query_summary=query_summary,
            )
            events.append(ev)
            emit(ev)
            return CapabilityResult(
                capability=cap.name,
                data=list(records),
                used_source=step.source,
                trace=events,
            )

        # Predicate rejected (rare; e.g. results not "good enough"). We treat
        # this like ``empty`` so the chain continues, but tag with a different
        # status so the trace is honest.
        ev = make_event(
            capability=cap.name,
            source=step.source,
            chain_position=step_idx,
            status="empty",
            latency_ms=latency_ms,
            result_count=len(records),
            why="predicate rejected: not sufficient",
            query_summary=query_summary,
        )
        events.append(ev)
        emit(ev)

    # All steps exhausted without satisfying the predicate.
    return CapabilityResult(
        capability=cap.name,
        data=[],
        used_source=None,
        trace=events,
    )
