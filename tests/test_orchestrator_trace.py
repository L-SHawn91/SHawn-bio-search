"""Tests for shawn_bio_search.orchestrator.trace + degradation."""

from __future__ import annotations

import json
import time

import pytest

from shawn_bio_search.orchestrator import degradation, trace


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """Redirect the persistent JSONL to a temp dir and clear collector state."""
    tmp_trace = tmp_path / "trace.jsonl"
    monkeypatch.setattr(trace, "DEFAULT_TRACE_PATH", tmp_trace)
    monkeypatch.delenv("SBS_TRACE_VERBOSE", raising=False)
    monkeypatch.delenv("SBS_TRACE_PERSIST", raising=False)
    trace.clear_run_collector()
    yield tmp_trace
    trace.clear_run_collector()


def _make_event(**overrides):
    payload = dict(
        capability="paper.by_doi",
        source="crossref",
        chain_position=0,
        status="success",
        latency_ms=42,
        result_count=1,
        why="primary",
    )
    payload.update(overrides)
    return trace.make_event(**payload)


def test_make_event_clamps_query_summary_and_status_marker():
    long_q = "x" * 500
    ev = trace.make_event(
        capability="paper.by_keywords",
        source="pubmed",
        chain_position=0,
        status="bogus_status",
        query_summary=long_q,
        why="hello",
    )
    assert len(ev.query_summary) == 200
    assert "[unknown_status=bogus_status]" in ev.why
    # Should still be constructable; trace must be tolerant.
    assert ev.status == "bogus_status"


def test_make_event_derives_latency_from_started_at():
    started = time.monotonic() - 0.05
    ev = trace.make_event(
        capability="x",
        source="y",
        chain_position=0,
        status="success",
        started_at=started,
    )
    assert ev.latency_ms >= 50


def test_run_collector_receives_emitted_events():
    buf = []
    trace.set_run_collector(trace.collect_into(buf))
    ev = _make_event()
    trace.emit(ev)
    assert buf == [ev]


def test_clear_run_collector_stops_capture():
    buf = []
    trace.set_run_collector(trace.collect_into(buf))
    trace.clear_run_collector()
    trace.emit(_make_event())
    assert buf == []


def test_collector_exception_does_not_propagate():
    def bad(_ev):
        raise RuntimeError("boom")

    trace.set_run_collector(bad)
    # Should not raise
    trace.emit(_make_event())


def test_persistent_jsonl_default_on(isolate_state):
    trace.emit(_make_event(status="success"))
    trace.emit(_make_event(status="empty", source="pubmed", chain_position=1))
    lines = isolate_state.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert [p["status"] for p in parsed] == ["success", "empty"]
    assert [p["source"] for p in parsed] == ["crossref", "pubmed"]


def test_persistent_jsonl_disabled_via_env(isolate_state, monkeypatch):
    monkeypatch.setenv("SBS_TRACE_PERSIST", "0")
    trace.emit(_make_event())
    assert not isolate_state.exists()


def test_stderr_disabled_by_default(isolate_state, capsys):
    trace.emit(_make_event())
    captured = capsys.readouterr()
    assert captured.err == ""


def test_stderr_enabled_via_env(isolate_state, monkeypatch, capsys):
    monkeypatch.setenv("SBS_TRACE_VERBOSE", "1")
    trace.emit(_make_event(status="missing_key", source="scopus", chain_position=2))
    captured = capsys.readouterr()
    assert "[trace]" in captured.err
    assert "scopus" in captured.err
    assert "missing_key" in captured.err
    assert "step=2" in captured.err


def test_iter_persistent_trace_round_trip(isolate_state):
    trace.emit(_make_event(status="success"))
    trace.emit(_make_event(status="http_5xx", chain_position=1))
    events = list(trace.iter_persistent_trace())
    assert [e.status for e in events] == ["success", "http_5xx"]
    last_one = list(trace.iter_persistent_trace(last_n=1))
    assert [e.status for e in last_one] == ["http_5xx"]


def test_iter_persistent_trace_skips_corrupt_lines(isolate_state):
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    with isolate_state.open("w", encoding="utf-8") as fh:
        fh.write('{"timestamp": 1.0, "capability": "x", "source": "y",'
                 ' "chain_position": 0, "status": "success"}\n')
        fh.write("not-json-at-all\n")
        fh.write("\n")
        fh.write('{"timestamp": 2.0, "capability": "x", "source": "y",'
                 ' "chain_position": 1, "status": "empty"}\n')
    events = list(trace.iter_persistent_trace())
    assert [e.status for e in events] == ["success", "empty"]


def test_prune_persistent_trace_drops_old_events(isolate_state):
    old = trace.make_event(
        capability="x", source="y", chain_position=0, status="success"
    )
    fresh = trace.make_event(
        capability="x", source="y", chain_position=1, status="success"
    )
    old.timestamp = time.time() - 200 * 86400
    isolate_state.parent.mkdir(parents=True, exist_ok=True)
    with isolate_state.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(old.to_jsonable()) + "\n")
        fh.write(json.dumps(fresh.to_jsonable()) + "\n")
    kept = trace.prune_persistent_trace(retention_days=90)
    assert kept == 1
    rem = list(trace.iter_persistent_trace())
    assert len(rem) == 1
    assert rem[0].chain_position == 1


def test_prune_missing_file_is_noop(tmp_path):
    missing = tmp_path / "nope.jsonl"
    assert trace.prune_persistent_trace(retention_days=30, path=missing) == 0


def test_event_extra_with_unserializable_value(isolate_state):
    class Weird:
        def __repr__(self):
            return "<weird>"

    ev = trace.make_event(
        capability="x",
        source="y",
        chain_position=0,
        status="success",
        extra={"obj": Weird()},
    )
    payload = ev.to_jsonable()
    json.dumps(payload)  # must not raise
    assert payload["extra"]["obj"] == "<weird>"


# ---------------------------------------------------------------------------
# Degradation report
# ---------------------------------------------------------------------------


def test_degradation_report_skipped_when_no_failures(tmp_path):
    out = tmp_path / "DEG.md"
    result = degradation.write_degradation_report(
        [_make_event(status="success"), _make_event(status="cache_hit")], out
    )
    assert result is None
    assert not out.exists()


def test_degradation_report_renders_failures(tmp_path):
    out = tmp_path / "DEG.md"
    events = [
        _make_event(status="success"),
        _make_event(status="missing_key", source="scopus", chain_position=0),
        _make_event(
            status="http_5xx",
            source="openalex",
            chain_position=1,
            http_status=503,
            error_kind="HTTPError",
            why="upstream down",
        ),
    ]
    result = degradation.write_degradation_report(events, out)
    assert result == out
    body = out.read_text(encoding="utf-8")
    assert "Total degradation events: **2**" in body
    assert "scopus" in body
    assert "openalex" in body
    assert "503" in body
    assert "upstream down" in body


def test_summarize_failures_counts():
    events = [
        _make_event(status="success"),
        _make_event(status="missing_key", source="scopus", chain_position=0),
        _make_event(status="missing_key", source="scopus", chain_position=0),
        _make_event(status="http_5xx", source="openalex", chain_position=1),
    ]
    summary = degradation.summarize_failures(events)
    assert summary["total"] == 3
    assert summary["by_source"]["scopus"] == 2
    assert summary["by_status"]["missing_key"] == 2
    assert summary["by_status"]["http_5xx"] == 1
