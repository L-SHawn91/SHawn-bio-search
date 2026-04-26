"""Tests for shawn_bio_search.orchestrator.runner.run_capability."""

from __future__ import annotations

import urllib.error

import pytest

from shawn_bio_search.orchestrator import (
    Capability,
    SourceStep,
    capabilities,
    clear_registry,
    register,
    run_capability,
    trace,
)


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    # Redirect persistent JSONL to tmp.
    monkeypatch.setattr(trace, "DEFAULT_TRACE_PATH", tmp_path / "trace.jsonl")
    monkeypatch.delenv("SBS_TRACE_VERBOSE", raising=False)
    monkeypatch.delenv("SBS_TRACE_PERSIST", raising=False)
    trace.clear_run_collector()
    clear_registry()
    yield
    trace.clear_run_collector()
    clear_registry()


def _capability(steps):
    """Build a one-off capability with the given (source, fetcher, why) steps."""
    chain = tuple(SourceStep(src, fn, why=why) for src, fn, why in steps)
    cap = Capability(name="test.cap", chain=chain)
    register(cap, replace=True)
    return cap


def test_first_success_short_circuits_chain():
    calls = []

    def step_a(_args):
        calls.append("a")
        return [{"id": 1}, {"id": 2}]

    def step_b(_args):
        calls.append("b")
        return [{"id": 99}]

    _capability([
        ("crossref", step_a, "primary"),
        ("openalex", step_b, "fallback"),
    ])
    result = run_capability("test.cap", query="anything")
    assert result.used_source == "crossref"
    assert [r["id"] for r in result.data] == [1, 2]
    assert calls == ["a"]
    statuses = [ev.status for ev in result.trace]
    assert statuses == ["success"]


def test_empty_primary_falls_through_to_secondary():
    def step_a(_args):
        return []

    def step_b(_args):
        return [{"id": 7}]

    _capability([
        ("crossref", step_a, "primary"),
        ("openalex", step_b, "fallback"),
    ])
    result = run_capability("test.cap", query="x")
    assert result.used_source == "openalex"
    assert result.data == [{"id": 7}]
    statuses = [ev.status for ev in result.trace]
    assert statuses == ["empty", "success"]


def test_missing_key_skips_step(monkeypatch):
    # Force the keyed source to be unconfigured.
    monkeypatch.delenv("CORE_API_KEY", raising=False)

    primary_called = False

    def step_core(_args):
        nonlocal primary_called
        primary_called = True
        return [{"id": "should-not-run"}]

    def step_pubmed(_args):
        return [{"id": "fallback"}]

    _capability([
        ("core", step_core, "needs key"),
        ("pubmed", step_pubmed, "free fallback"),
    ])
    result = run_capability("test.cap", query="x")
    assert primary_called is False
    assert result.used_source == "pubmed"
    statuses = [ev.status for ev in result.trace]
    assert statuses == ["missing_key", "success"]
    miss_ev = result.trace[0]
    assert miss_ev.extra.get("missing_env") == ["CORE_API_KEY"]


def test_http_4xx_classified_and_chain_continues():
    def step_a(_args):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    def step_b(_args):
        return [{"id": "ok"}]

    _capability([
        ("crossref", step_a, "primary"),
        ("openalex", step_b, "fallback"),
    ])
    result = run_capability("test.cap", query="x")
    assert result.used_source == "openalex"
    statuses = [ev.status for ev in result.trace]
    assert statuses == ["http_4xx", "success"]
    assert result.trace[0].http_status == 404
    assert result.trace[0].error_kind == "HTTPError"


def test_http_5xx_classified():
    def step_a(_args):
        raise urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)

    def step_b(_args):
        return [{"id": "x"}]

    _capability([
        ("crossref", step_a, ""),
        ("openalex", step_b, ""),
    ])
    result = run_capability("test.cap", query="x")
    assert [ev.status for ev in result.trace] == ["http_5xx", "success"]


def test_throttled_classified():
    def step_a(_args):
        raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)

    def step_b(_args):
        return [{"id": "x"}]

    _capability([
        ("crossref", step_a, ""),
        ("openalex", step_b, ""),
    ])
    result = run_capability("test.cap", query="x")
    assert result.trace[0].status == "throttled"


def test_timeout_classified():
    def step_a(_args):
        raise TimeoutError("slow")

    def step_b(_args):
        return [{"id": "x"}]

    _capability([
        ("crossref", step_a, ""),
        ("openalex", step_b, ""),
    ])
    result = run_capability("test.cap", query="x")
    assert result.trace[0].status == "timeout"


def test_url_error_with_timed_out_reason_classified_as_timeout():
    def step_a(_args):
        raise urllib.error.URLError("the read timed out")

    def step_b(_args):
        return [{"id": "x"}]

    _capability([
        ("crossref", step_a, ""),
        ("openalex", step_b, ""),
    ])
    result = run_capability("test.cap", query="x")
    assert result.trace[0].status == "timeout"


def test_arbitrary_exception_classified_as_exception():
    def step_a(_args):
        raise ValueError("bad data")

    def step_b(_args):
        return [{"id": "x"}]

    _capability([
        ("crossref", step_a, ""),
        ("openalex", step_b, ""),
    ])
    result = run_capability("test.cap", query="x")
    assert result.trace[0].status == "exception"
    assert result.trace[0].error_kind == "ValueError"


def test_all_steps_fail_returns_no_data():
    def step_a(_args):
        return []

    def step_b(_args):
        raise urllib.error.HTTPError("u", 503, "down", {}, None)

    _capability([
        ("pubmed", step_a, ""),
        ("openalex", step_b, ""),
    ])
    result = run_capability("test.cap", query="x")
    assert result.data == []
    assert result.used_source is None
    assert result.succeeded is False
    statuses = [ev.status for ev in result.trace]
    assert statuses == ["empty", "http_5xx"]


def test_predicate_rejection_continues_chain():
    def predicate(records, _args):
        # Require at least 2 results.
        return len(records) >= 2

    chain = (
        SourceStep("pubmed", lambda _args: [{"id": "single"}], why="primary"),
        SourceStep(
            "openalex",
            lambda _args: [{"id": "a"}, {"id": "b"}],
            why="fallback",
        ),
    )
    cap = Capability(name="test.cap", chain=chain, success_predicate=predicate)
    register(cap, replace=True)
    result = run_capability("test.cap", query="x")
    assert result.used_source == "openalex"
    statuses = [ev.status for ev in result.trace]
    # Primary returns 1 record → predicate rejects → status=empty (with rejection note)
    assert statuses == ["empty", "success"]
    assert "predicate rejected" in result.trace[0].why


def test_run_collector_receives_all_step_events():
    collected = []
    trace.set_run_collector(trace.collect_into(collected))

    _capability([
        ("pubmed", lambda _args: [], "p"),
        ("openalex", lambda _args: [{"id": "ok"}], "o"),
    ])
    run_capability("test.cap", query="x")
    statuses = [ev.status for ev in collected]
    assert statuses == ["empty", "success"]


def test_query_summary_truncated_and_present_in_trace():
    long_q = "x" * 500

    _capability([("pubmed", lambda _args: [{"id": 1}], "p")])
    result = run_capability("test.cap", query=long_q)
    assert len(result.trace[0].query_summary) <= 200
    assert result.trace[0].query_summary.startswith("query=")


def test_runner_uses_extra_kwargs_for_doi_capability(monkeypatch):
    """Smoke: the seed paper.by_doi capability should accept doi=... and route
    it through, even if the underlying fetchers fail (we mock them all)."""
    capabilities._install_seed_capabilities()

    # Replace all fetchers in paper.by_doi with stubs.
    cap = capabilities.get("paper.by_doi")
    stubbed = Capability(
        name="paper.by_doi",
        chain=tuple(
            SourceStep(
                step.source,
                lambda _args, src=step.source: [{"src": src, "doi": _args.get("doi")}],
                why=step.why,
            )
            for step in cap.chain
        ),
    )
    register(stubbed, replace=True)
    result = run_capability("paper.by_doi", doi="10.1038/ncb3516")
    assert result.used_source == stubbed.chain[0].source  # primary wins
    assert result.data[0]["doi"] == "10.1038/ncb3516"
