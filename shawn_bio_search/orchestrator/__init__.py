"""Capability orchestration: cross-source fallback, trace, degradation reporting.

Phase 4 PR A introduces only the trace event bus + degradation report.
Capability registry and runner arrive in PR B.
"""

from __future__ import annotations

from .trace import (
    TraceEvent,
    emit,
    set_run_collector,
    clear_run_collector,
    iter_persistent_trace,
    prune_persistent_trace,
    DEFAULT_TRACE_PATH,
)
from .degradation import (
    write_degradation_report,
    summarize_failures,
)

__all__ = [
    "TraceEvent",
    "emit",
    "set_run_collector",
    "clear_run_collector",
    "iter_persistent_trace",
    "prune_persistent_trace",
    "DEFAULT_TRACE_PATH",
    "write_degradation_report",
    "summarize_failures",
]
