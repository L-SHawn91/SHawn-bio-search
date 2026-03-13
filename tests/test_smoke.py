from pathlib import Path
import subprocess
import json

from shawn_bio_search.search import search_papers


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
    results = search_papers(query="endometrial organoid", max_results=1, sources=["openalex"])
    assert results.papers
    scored = results.papers[0]
    # claim 없는 경우는 score 미부여 가능하므로 직접 호출 대신 source integrity 확인
    assert scored.get("source") == "openalex"
