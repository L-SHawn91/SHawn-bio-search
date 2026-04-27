from shawn_bio_search.llm_triage import (
    code_triage_paper,
    split_model_chain,
    triage_papers,
    _ollama_num_predict,
    _ollama_think_for_model,
)


def _paper():
    return {
        "title": "Endometrial organoids model uterine biology",
        "abstract": "Endometrial organoids preserve epithelial differentiation and respond to hormonal cues.",
        "doi": "10.1000/example",
        "evidence_score": 0.42,
        "claim_overlap": 0.31,
        "hypothesis_overlap": 0.18,
        "support_score": 0.27,
        "contradiction_score": 0.02,
        "evidence_label": "support",
        "best_support_sentence": "Endometrial organoids preserve epithelial differentiation and respond to hormonal cues.",
    }


def test_split_model_chain_appends_code_and_dedupes():
    chain = split_model_chain(
        model="gpt-oss:120b-cloud",
        fallback_chain="gpt-oss:120b-cloud,gpt-oss:20b-cloud,qwen3:8b",
    )
    assert chain == ["gpt-oss:120b-cloud", "gpt-oss:20b-cloud", "qwen3:8b", "code"]


def test_code_triage_returns_search_safe_fields():
    result = code_triage_paper(
        _paper(),
        query="endometrial organoid",
        claim="endometrial organoids model uterine biology",
    )
    assert result["llm_provider"] == "code"
    assert result["llm_model_used"] == "code"
    assert 0.0 <= result["llm_relevance"] <= 1.0
    assert result["llm_direction"] == "support"
    assert result["llm_reason"]


def test_triage_papers_uses_ollama_result_when_available(monkeypatch):
    def fake_call(**kwargs):
        return {
            "relevance": 0.91,
            "direction": "support",
            "reason": "Directly addresses the organoid claim",
            "risk": "Single abstract only",
        }

    monkeypatch.setattr("shawn_bio_search.llm_triage._call_ollama_model", fake_call)
    papers, meta = triage_papers(
        [_paper()],
        query="endometrial organoid",
        claim="endometrial organoids model uterine biology",
        enabled=True,
        model="gpt-oss:20b-cloud",
        fallback_chain="gpt-oss:20b-cloud,code",
        limit=1,
    )
    assert meta["enabled"] is True
    assert meta["counts"] == {"gpt-oss:20b-cloud": 1}
    assert papers[0]["llm_provider"] == "ollama"
    assert papers[0]["llm_relevance"] == 0.91


def test_triage_papers_falls_back_to_code_when_ollama_fails(monkeypatch):
    def fake_call(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("shawn_bio_search.llm_triage._call_ollama_model", fake_call)
    papers, meta = triage_papers(
        [_paper()],
        query="endometrial organoid",
        claim="endometrial organoids model uterine biology",
        enabled=True,
        model="gpt-oss:20b-cloud",
        fallback_chain="gpt-oss:20b-cloud,code",
        limit=1,
    )
    assert meta["counts"] == {"code": 1}
    assert papers[0]["llm_provider"] == "code"
    assert "offline" in papers[0]["llm_triage_warning"]


def test_ollama_runtime_options_follow_environment(monkeypatch):
    monkeypatch.setenv("SBS_LLM_THINK", "false")
    monkeypatch.setenv("SBS_LLM_NUM_PREDICT", "768")

    assert _ollama_think_for_model("gpt-oss:120b-cloud") is False
    assert _ollama_num_predict() == 768
