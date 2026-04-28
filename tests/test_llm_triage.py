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


def test_code_triage_offtopic_liver_classified_mention_only():
    """Liver/hepatic paper must be classified mention-only for endometrial query."""
    paper = {
        "title": "Hepatocellular carcinoma sorafenib resistance liver LIHC TCGA",
        "abstract": "Hepatic hepatoma cirrhosis biliary liver HCC sorafenib drug resistance.",
        "doi": "10.1000/liver",
        "evidence_score": 0.25,
        "claim_overlap": 0.18,
        "hypothesis_overlap": 0.05,
        "support_score": 0.12,
        "contradiction_score": 0.01,
        "evidence_label": "uncertain",
    }
    result = code_triage_paper(
        paper,
        query="endometrial cancer endometriosis RIF implantation failure",
        claim="Endometrial transcriptomics reveals molecular basis of cancer",
    )
    assert result["llm_direction"] == "mention-only"
    assert result["llm_relevance"] <= 0.10


def test_code_triage_prostate_classified_mention_only():
    """Prostate paper must be classified mention-only for endometrial query."""
    paper = {
        "title": "Prostate cancer androgen deprivation therapy prostatic CRPC",
        "abstract": "Prostatic adenocarcinoma castration-resistant enzalutamide resistance.",
        "doi": "10.1000/prostate",
        "evidence_score": 0.22,
        "claim_overlap": 0.15,
        "hypothesis_overlap": 0.04,
        "support_score": 0.10,
        "contradiction_score": 0.01,
        "evidence_label": "uncertain",
    }
    result = code_triage_paper(
        paper,
        query="endometrial cancer endometriosis receptivity WOI",
        claim="Endometrial transcriptomics reveals molecular basis of cancer",
    )
    assert result["llm_direction"] == "mention-only"
    assert result["llm_relevance"] <= 0.10


def test_code_triage_plant_classified_mention_only():
    """Plant paper must be classified mention-only for endometrial query."""
    paper = {
        "title": "Arabidopsis thaliana drought stress photosynthesis chloroplast",
        "abstract": "Plant seedling wheat germination tillering ROS osmotic tolerance.",
        "doi": "10.1000/plant",
        "evidence_score": 0.18,
        "claim_overlap": 0.10,
        "hypothesis_overlap": 0.02,
        "support_score": 0.08,
        "contradiction_score": 0.00,
        "evidence_label": "mention-only",
    }
    result = code_triage_paper(
        paper,
        query="endometrial cancer endometriosis uterine biology",
        claim="Endometrial transcriptomics",
    )
    assert result["llm_direction"] == "mention-only"


def test_code_triage_offtopic_guard_skipped_when_query_mentions_tissue():
    """If query explicitly mentions hepatic/liver, liver paper should NOT be filtered."""
    paper = {
        "title": "Hepatic gene expression endometrial decidualization liver organoid",
        "abstract": "Liver hepatic organoid model of endometrial stromal cells.",
        "doi": "10.1000/combo",
        "evidence_score": 0.45,
        "claim_overlap": 0.30,
        "hypothesis_overlap": 0.20,
        "support_score": 0.25,
        "contradiction_score": 0.02,
        "evidence_label": "support",
    }
    result = code_triage_paper(
        paper,
        query="hepatic endometrial organoid liver decidualization",
        claim="Hepatic endometrial organoid cross-species model",
    )
    # Guard is skipped because query contains 'liver'/'hepatic'
    assert result["llm_direction"] != "mention-only"
