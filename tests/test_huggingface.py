"""Offline tests for the HuggingFace dataset source."""

from __future__ import annotations

import pytest

from shawn_bio_search.sources import huggingface as hf


SAMPLE_HF_RESPONSE = [
    {
        "id": "bigbio/pubmed_qa",
        "lastModified": "2024-08-12T10:11:12.000Z",
        "downloads": 12450,
        "likes": 87,
        "tags": [
            "task_categories:question-answering",
            "language:en",
            "license:mit",
            "size_categories:10K<n<100K",
            "biology",
            "human-genome",
        ],
        "description": "Biomedical question-answering dataset derived from PubMed abstracts.",
        "cardData": {"pretty_name": "PubMedQA"},
    },
    {
        "id": "bigbio/medqa",
        "lastModified": "2023-05-01T00:00:00.000Z",
        "downloads": 5400,
        "likes": 31,
        "tags": ["task_categories:multiple-choice"],
        "description": "Medical multiple-choice questions from USMLE-style exams.",
    },
]


def _patch_http(monkeypatch, payload, calls=None):
    def _fake(url, headers=None, **kwargs):
        if calls is not None:
            calls.append({"url": url, "headers": headers})
        return payload
    monkeypatch.setattr(hf, "http_json", _fake)


def test_fetch_returns_normalized_records(monkeypatch):
    _patch_http(monkeypatch, SAMPLE_HF_RESPONSE)
    out = hf.fetch_huggingface_datasets("pubmed", limit=10)
    assert len(out) == 2
    first = out[0]
    assert first["repository"] == "huggingface"
    assert first["accession"] == "bigbio/pubmed_qa"
    assert first["title"] == "PubMedQA"
    assert first["assay"] == "question-answering"
    assert "human-genome" in first["organism"]
    assert first["year"] == 2024
    assert first["url"] == "https://huggingface.co/datasets/bigbio/pubmed_qa"
    assert first["downloads"] == 12450


def test_fetch_falls_back_to_id_when_no_pretty_name(monkeypatch):
    _patch_http(monkeypatch, SAMPLE_HF_RESPONSE)
    out = hf.fetch_huggingface_datasets("medqa", limit=5)
    second = next(r for r in out if r["accession"] == "bigbio/medqa")
    assert second["title"] == "bigbio/medqa"
    assert second["assay"] == "multiple-choice"


def test_empty_query_short_circuits(monkeypatch):
    called = {"hit": False}
    def _no_call(*a, **kw):
        called["hit"] = True
        return []
    monkeypatch.setattr(hf, "http_json", _no_call)
    assert hf.fetch_huggingface_datasets("", limit=5) == []
    assert hf.fetch_huggingface_datasets("   ", limit=5) == []
    assert called["hit"] is False


def test_http_error_returns_empty_not_raise(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("503")
    monkeypatch.setattr(hf, "http_json", _boom)
    assert hf.fetch_huggingface_datasets("anything", limit=5) == []


def test_non_list_payload_returns_empty(monkeypatch):
    _patch_http(monkeypatch, {"error": "rate limited"})
    assert hf.fetch_huggingface_datasets("x", limit=5) == []


def test_auth_header_added_when_token_present(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_secret_xyz")
    calls = []
    _patch_http(monkeypatch, SAMPLE_HF_RESPONSE, calls=calls)
    hf.fetch_huggingface_datasets("pubmed", limit=5)
    assert calls[0]["headers"] == {"Authorization": "Bearer hf_secret_xyz"}


def test_auth_header_omitted_without_token(monkeypatch):
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    calls = []
    _patch_http(monkeypatch, SAMPLE_HF_RESPONSE, calls=calls)
    hf.fetch_huggingface_datasets("pubmed", limit=5)
    assert calls[0]["headers"] == {}


def test_summary_truncates_long_description(monkeypatch):
    long_desc = "X" * 800
    payload = [{
        "id": "huge/dataset",
        "lastModified": "2024-01-01T00:00:00.000Z",
        "tags": [],
        "description": long_desc,
    }]
    _patch_http(monkeypatch, payload)
    out = hf.fetch_huggingface_datasets("huge", limit=1)
    assert len(out[0]["summary"]) <= 601
    assert out[0]["summary"].endswith("…")
