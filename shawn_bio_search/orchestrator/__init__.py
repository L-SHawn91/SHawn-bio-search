"""Capability orchestration: cross-source fallback, trace, degradation reporting.

Phase 4 PR A introduced the trace event bus + degradation report.
PR B adds the capability registry and runner.
"""

from __future__ import annotations

from .capabilities import (
    Capability,
    SourceStep,
    register,
    get,
    list_capabilities,
    clear_registry,
    missing_required_keys,
)
from .degradation import (
    summarize_failures,
    write_degradation_report,
)
from .runner import (
    CapabilityResult,
    run_capability,
)
from .trace import (
    DEFAULT_TRACE_PATH,
    TraceEvent,
    clear_run_collector,
    emit,
    iter_persistent_trace,
    prune_persistent_trace,
    set_run_collector,
)

__all__ = [
    "Capability",
    "CapabilityResult",
    "DEFAULT_TRACE_PATH",
    "SourceStep",
    "TraceEvent",
    "clear_registry",
    "clear_run_collector",
    "emit",
    "get",
    "iter_persistent_trace",
    "list_capabilities",
    "missing_required_keys",
    "prune_persistent_trace",
    "register",
    "run_capability",
    "set_run_collector",
    "summarize_failures",
    "write_degradation_report",
]
