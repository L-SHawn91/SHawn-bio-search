"""Degradation report: distill failed/skipped trace events into a markdown file.

A degradation event is any :class:`TraceEvent` whose ``is_failure`` is true:
non-success and not the deliberate ``skipped`` marker. The report is only
written when at least one such event exists; otherwise the destination path is
left untouched and the function returns ``None``.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, List, Optional

from .trace import TraceEvent, filter_failures


def summarize_failures(events: Iterable[TraceEvent]) -> dict:
    """Aggregate failure events for templated output.

    Returns a dict with:
    - ``total``: failure count
    - ``by_source``: ``{source: count}`` sorted by count desc
    - ``by_status``: ``{status: count}``
    - ``by_capability``: ``{capability: count}``
    - ``events``: list of original events (in chronological order)
    """
    failures = filter_failures(list(events))
    by_source: Counter = Counter()
    by_status: Counter = Counter()
    by_capability: Counter = Counter()
    for ev in failures:
        by_source[ev.source] += 1
        by_status[ev.status] += 1
        by_capability[ev.capability] += 1
    return {
        "total": len(failures),
        "by_source": dict(by_source.most_common()),
        "by_status": dict(by_status.most_common()),
        "by_capability": dict(by_capability.most_common()),
        "events": failures,
    }


def _render_markdown(summary: dict, *, title: str) -> str:
    lines: List[str] = [
        f"# {title}",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime())}",
        f"Total degradation events: **{summary['total']}**",
        "",
    ]

    if summary["by_status"]:
        lines += [
            "## By status",
            "",
            "| status | count |",
            "|---|---:|",
        ]
        for status, count in summary["by_status"].items():
            lines.append(f"| `{status}` | {count} |")
        lines.append("")

    if summary["by_source"]:
        lines += [
            "## By source",
            "",
            "| source | count |",
            "|---|---:|",
        ]
        for source, count in summary["by_source"].items():
            lines.append(f"| `{source}` | {count} |")
        lines.append("")

    if summary["by_capability"]:
        lines += [
            "## By capability",
            "",
            "| capability | count |",
            "|---|---:|",
        ]
        for cap, count in summary["by_capability"].items():
            lines.append(f"| `{cap}` | {count} |")
        lines.append("")

    events: List[TraceEvent] = summary["events"]
    if events:
        lines += [
            "## Events",
            "",
            "| time | capability | step | source | status | latency | http | error | why |",
            "|---|---|---:|---|---|---:|---:|---|---|",
        ]
        # Group label per-capability for readability isn't necessary in the
        # table; but we keep insertion order. ``defaultdict`` here only to
        # appease lints; not used otherwise.
        _ = defaultdict(list)
        for ev in events:
            ts = time.strftime("%H:%M:%S", time.localtime(ev.timestamp))
            http = "" if ev.http_status is None else str(ev.http_status)
            err = ev.error_kind or ""
            why = (ev.why or "").replace("|", "\\|")
            lines.append(
                f"| {ts} | `{ev.capability}` | {ev.chain_position} "
                f"| `{ev.source}` | `{ev.status}` | {ev.latency_ms}ms "
                f"| {http} | {err} | {why} |"
            )
        lines.append("")

    return "\n".join(lines)


def write_degradation_report(
    events: Iterable[TraceEvent],
    out_path: Path,
    *,
    title: str = "Degradation report",
) -> Optional[Path]:
    """Write a degradation markdown file. Returns the path on success, else None.

    No file is created when there are zero failures — the caller can rely on
    the file's existence as the "did anything degrade" signal.
    """
    summary = summarize_failures(events)
    if summary["total"] == 0:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_markdown(summary, title=title), encoding="utf-8")
    return out_path
