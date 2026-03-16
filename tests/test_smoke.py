from pathlib import Path
import subprocess
import json

from shawn_bio_search.search import search_papers
from shawn_bio_search.query_expansion import expand_query


def test_cli_help():
    r = subprocess.run(["shawn-bio-search", "-h"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "usage" in r.stdout.lower() or "usage" in r.stderr.lower()


def test_search_bundle_smoke(tmp_path: Path):
    out = tmp_path / "bundle.json"
    cmd = [
        "python3",
        "scripts/search_bundle.py",
        "--query",
        "adenomyosis",
        "--claim",
        "adenomyosis affects fertility outcomes",
        "--hypothesis",
        "adenomyosis may reduce IVF success",
        "--fast",
        "--no-semantic-scholar",
        "--out",
        str(out),
    ]
    r = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    assert "papers" in data


def test_score_fields_present():
    results = search_papers(
        query="endometrial organoid",
        claim="endometrial organoids model uterine biology",
        max_results=1,
        sources=["openalex"],
    )
    assert results.papers
    scored = results.papers[0]
    assert scored.get("source") == "openalex"
    assert scored.get("evidence_label") in {"support", "contradict", "uncertain", "mention-only"}


def test_query_expansion_has_expected_terms():
    expanded = expand_query("endometrial organoid")
    assert "endometrium" in expanded.lower() or "uterine" in expanded.lower()


def test_project_mode_sets_effective_query_metadata():
    results = search_papers(
        query="organoid",
        max_results=1,
        sources=["openalex"],
        project_mode="endometrial-organoid-review",
        expand=True,
    )
    assert results.data.get("project_mode") == "endometrial-organoid-review"
    assert results.data.get("query_expanded") is True
    assert "effective_query" in results.data
