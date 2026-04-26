"""Offline tests for the Kaggle dataset source."""

from __future__ import annotations

import base64

import pytest

from shawn_bio_search.sources import kaggle


SAMPLE_KAGGLE_RESPONSE = [
    {
        "ref": "andrewmvd/medical-mnist",
        "title": "Medical MNIST",
        "subtitle": "58,954 medical images in 6 classes",
        "description": "Medical image classification benchmark derived from public sources.",
        "lastUpdated": "2024-09-15T10:11:12.000Z",
        "downloadCount": 35200,
        "voteCount": 412,
        "ownerName": "Andrew",
        "url": "/datasets/andrewmvd/medical-mnist",
        "tags": [
            {"name": "medical"},
            {"name": "image classification"},
            {"name": "human"},
        ],
    },
    {
        "ref": "lab/chest-xray",
        "title": "Chest X-Ray Pneumonia",
        "subtitle": "Pediatric pneumonia X-rays",
        "description": "Pediatric chest X-rays labeled for pneumonia.",
        "lastUpdated": "2023-02-01T00:00:00.000Z",
        "downloadCount": 12000,
        "voteCount": 100,
        "tags": ["xray", "pediatric"],
    },
]


def _patch_http(monkeypatch, payload, calls=None):
    def _fake(url, headers=None, **kwargs):
        if calls is not None:
            calls.append({"url": url, "headers": headers})
        return payload
    monkeypatch.setattr(kaggle, "http_json", _fake)


def _set_creds(monkeypatch, user="myuser", key="mykey"):
    monkeypatch.setenv("KAGGLE_USERNAME", user)
    monkeypatch.setenv("KAGGLE_KEY", key)


def test_no_credentials_short_circuits(monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    called = {"hit": False}
    def _no_call(*a, **kw):
        called["hit"] = True
        return []
    monkeypatch.setattr(kaggle, "http_json", _no_call)
    assert kaggle.fetch_kaggle_datasets("anything") == []
    assert called["hit"] is False


def test_partial_credentials_short_circuits(monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "alice")
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    assert kaggle.fetch_kaggle_datasets("anything") == []


def test_empty_query_short_circuits(monkeypatch):
    _set_creds(monkeypatch)
    called = {"hit": False}
    def _no_call(*a, **kw):
        called["hit"] = True
        return []
    monkeypatch.setattr(kaggle, "http_json", _no_call)
    assert kaggle.fetch_kaggle_datasets("") == []
    assert kaggle.fetch_kaggle_datasets("   ") == []
    assert called["hit"] is False


def test_basic_auth_header_added(monkeypatch):
    _set_creds(monkeypatch, user="alice", key="secret")
    calls = []
    _patch_http(monkeypatch, SAMPLE_KAGGLE_RESPONSE, calls=calls)
    kaggle.fetch_kaggle_datasets("medical")
    expected = base64.b64encode(b"alice:secret").decode("ascii")
    assert calls[0]["headers"] == {"Authorization": f"Basic {expected}"}


def test_normalization_round_trip(monkeypatch):
    _set_creds(monkeypatch)
    _patch_http(monkeypatch, SAMPLE_KAGGLE_RESPONSE)
    out = kaggle.fetch_kaggle_datasets("medical", limit=5)
    assert len(out) == 2
    first = out[0]
    assert first["repository"] == "kaggle"
    assert first["accession"] == "andrewmvd/medical-mnist"
    assert first["title"] == "Medical MNIST"
    assert first["year"] == 2024
    assert first["downloads"] == 35200
    assert first["votes"] == 412
    assert first["owner"] == "Andrew"
    assert first["url"] == "https://www.kaggle.com/datasets/andrewmvd/medical-mnist"
    assert "human" in first["organism"]
    assert first["assay"] == "medical"


def test_string_tags_are_handled(monkeypatch):
    _set_creds(monkeypatch)
    _patch_http(monkeypatch, SAMPLE_KAGGLE_RESPONSE)
    out = kaggle.fetch_kaggle_datasets("xray")
    second = next(r for r in out if r["accession"] == "lab/chest-xray")
    assert second["assay"] == "xray"
    assert second["organism"] == ""  # no bio-hint tokens in {xray, pediatric}


def test_http_error_returns_empty(monkeypatch):
    _set_creds(monkeypatch)
    def _boom(*a, **kw):
        raise RuntimeError("503")
    monkeypatch.setattr(kaggle, "http_json", _boom)
    assert kaggle.fetch_kaggle_datasets("anything") == []


def test_non_list_payload_returns_empty(monkeypatch):
    _set_creds(monkeypatch)
    _patch_http(monkeypatch, {"error": "rate limited"})
    assert kaggle.fetch_kaggle_datasets("x") == []


def test_limit_caps_results(monkeypatch):
    _set_creds(monkeypatch)
    _patch_http(monkeypatch, SAMPLE_KAGGLE_RESPONSE)
    out = kaggle.fetch_kaggle_datasets("medical", limit=1)
    assert len(out) == 1


def test_url_field_normalization(monkeypatch):
    _set_creds(monkeypatch)
    payload = [{
        "ref": "team/no-url",
        "title": "Bare ref",
        "lastUpdated": "2024-01-01T00:00:00.000Z",
        "tags": [],
    }]
    _patch_http(monkeypatch, payload)
    out = kaggle.fetch_kaggle_datasets("bare")
    assert out[0]["url"] == "https://www.kaggle.com/datasets/team/no-url"
