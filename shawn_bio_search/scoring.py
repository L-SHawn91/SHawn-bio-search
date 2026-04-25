"""Scoring module for claim-level evidence evaluation."""

import re
from typing import Any, Dict, List

from .text_utils import overlap_ratio, tokenize


_NEG_TERMS = {
    "not", "no", "without", "lack", "lacks", "failed", "fail", "fails",
    "reduced", "decrease", "decreased", "lower", "suppressed",
    "inhibit", "inhibited", "inhibits",
}

_SOURCE_WEIGHTS = {
    "pubmed": 1.0,
    "europe_pmc": 0.96,
    "openalex": 0.95,
    "semantic_scholar": 0.98,
    "crossref": 0.9,
    "scopus": 0.97,
    "google_scholar": 0.82,
    "clinicaltrials": 0.9,
    "biorxiv": 0.84,
    "medrxiv": 0.84,
    "arxiv": 0.82,
    "openaire": 0.9,
    "core": 0.88,
    "unpaywall": 0.9,
    "f1000research": 0.92,
    "doaj": 0.9,
}


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    cleaned = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if len(p.strip()) >= 30]


def _claim_is_negative(claim: str) -> bool:
    return any(t in tokenize(claim) for t in _NEG_TERMS)


def _sentence_analysis(claim: str, hypothesis: str, text: str) -> Dict[str, Any]:
    """Analyze sentences for support/contradiction."""
    sentences = _split_sentences(text)
    if not claim or not sentences:
        return {
            "support_score": 0.0,
            "contradiction_score": 0.0,
            "best_support_sentence": "",
            "best_contradict_sentence": "",
            "hypothesis_sentence_overlap": 0.0,
            "stage2_score": 0.0,
        }
    
    claim_neg = _claim_is_negative(claim)
    best_support = (0.0, "")
    best_contra = (0.0, "")
    best_hyp = 0.0
    
    for s in sentences:
        ov = overlap_ratio(claim, s)
        hov = overlap_ratio(hypothesis, s) if hypothesis else 0.0
        stoks = tokenize(s)
        has_neg = any(t in _NEG_TERMS for t in stoks)
        
        support = ov
        contra = 0.0
        if claim_neg:
            if not has_neg:
                contra = ov * 0.85
        else:
            if has_neg:
                contra = ov * 0.85
        
        if support > best_support[0]:
            best_support = (support, s)
        if contra > best_contra[0]:
            best_contra = (contra, s)
        if hov > best_hyp:
            best_hyp = hov
    
    stage2 = max(0.0, best_support[0] - 0.7 * best_contra[0] + 0.25 * best_hyp)
    
    return {
        "support_score": round(best_support[0], 4),
        "contradiction_score": round(best_contra[0], 4),
        "best_support_sentence": best_support[1],
        "best_contradict_sentence": best_contra[1],
        "hypothesis_sentence_overlap": round(best_hyp, 4),
        "stage2_score": round(min(stage2, 1.0), 4),
    }


def classify_evidence_label(support_score: float, contradiction_score: float, evidence_score: float, has_claim: bool) -> str:
    """Classify evidence into four practical buckets."""
    if not has_claim:
        return "mention-only"
    if support_score >= 0.18 and support_score > contradiction_score * 1.15:
        return "support"
    if contradiction_score >= 0.18 and contradiction_score > support_score * 1.15:
        return "contradict"
    if evidence_score >= 0.12 or support_score >= 0.08 or contradiction_score >= 0.08:
        return "uncertain"
    return "mention-only"


def score_paper(paper: Dict[str, Any], claim: str, hypothesis: str) -> Dict[str, Any]:
    """Score a paper for claim/hypothesis relevance."""
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".strip()

    claim_overlap = overlap_ratio(claim, text) if claim else 0.0
    hypothesis_overlap = overlap_ratio(hypothesis, text) if hypothesis else 0.0

    citations = paper.get("citations") or 0
    if isinstance(citations, str) and citations.isdigit():
        citations = int(citations)
    if not isinstance(citations, int):
        citations = 0

    source = (paper.get("source") or "").strip().lower()
    source_weight = _SOURCE_WEIGHTS.get(source, 0.88)
    has_doi = bool((paper.get("doi") or "").strip())
    has_abstract = bool((paper.get("abstract") or "").strip())
    metadata_bonus = 0.03 * float(has_doi) + 0.04 * float(has_abstract)

    cite_component = min(citations, 500) / 500.0
    stage1_raw = 0.50 * claim_overlap + 0.20 * hypothesis_overlap + 0.20 * cite_component + 0.10 * source_weight + metadata_bonus
    stage1 = round(min(stage1_raw, 1.0), 4)

    s2 = _sentence_analysis(claim, hypothesis, paper.get("abstract") or "")

    if claim and has_abstract:
        evidence_score = round(min(0.40 * stage1 + 0.60 * s2["stage2_score"], 1.0), 4)
    else:
        evidence_score = stage1
    
    paper["claim_overlap"] = round(claim_overlap, 4)
    paper["hypothesis_overlap"] = round(hypothesis_overlap, 4)
    paper["source_weight"] = round(source_weight, 4)
    paper["metadata_bonus"] = round(metadata_bonus, 4)
    paper["stage1_score"] = stage1
    paper["stage2_score"] = s2["stage2_score"]
    paper["support_score"] = s2["support_score"]
    paper["contradiction_score"] = s2["contradiction_score"]
    paper["best_support_sentence"] = s2["best_support_sentence"]
    paper["best_contradict_sentence"] = s2["best_contradict_sentence"]
    paper["hypothesis_sentence_overlap"] = s2["hypothesis_sentence_overlap"]
    paper["evidence_score"] = evidence_score
    paper["evidence_label"] = classify_evidence_label(
        support_score=s2["support_score"],
        contradiction_score=s2["contradiction_score"],
        evidence_score=evidence_score,
        has_claim=bool(claim.strip()),
    )

    return paper
