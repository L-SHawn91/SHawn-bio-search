"""Scoring module for claim-level evidence evaluation."""

import csv
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

from .text_utils import overlap_ratio, tokenize
from .embeddings import embed_texts, cosine_sim

_GUARD_LOG = Path(__file__).resolve().parents[2] / "outputs" / "topic_guard_false_positives.tsv"


_NEG_TERMS = {
    "not", "no", "without", "lack", "lacks", "failed", "fail", "fails",
    "reduced", "decrease", "decreased", "lower", "suppressed",
    "inhibit", "inhibited", "inhibits",
}

# semantic_scholar lowered from 0.98 → 0.88: it has broad coverage but returns
# many off-topic results for narrow biomedical queries; bringing it in line with
# other moderate-quality sources reduces false positives without excluding it.
_SOURCE_WEIGHTS = {
    "pubmed": 1.0,
    "europe_pmc": 0.96,
    "openalex": 0.95,
    "semantic_scholar": 0.88,
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

# ---------------------------------------------------------------------------
# Topic guard — negative organism/tissue filter
# ---------------------------------------------------------------------------
# Each entry is (guard_tokens, guard_phrase).  A paper matches the guard when
# ANY of its tokens appears in the paper title+abstract.  If the query also
# contains any of those tokens the guard is skipped (the user explicitly asked
# about that topic).

_TOPIC_GUARD_GROUPS: List[Dict[str, Any]] = [
    {
        "label": "plant",
        "tokens": frozenset({"plant", "plants", "wheat", "barley", "rice", "maize",
                              "corn", "arabidopsis", "soybean", "tobacco", "potato",
                              "tomato", "phytohormone", "phytochemical", "photosynthesis",
                              "chloroplast", "seedling", "germination", "tillering"}),
    },
    {
        "label": "prostate",
        "tokens": frozenset({"prostate", "prostatic"}),
    },
    {
        "label": "cervical",
        "tokens": frozenset({"cervical", "cervix"}),
    },
    {
        "label": "hepatic",
        "tokens": frozenset({"hepatic", "hepatocyte", "hepatocytes", "liver",
                              "hepatoma", "cirrhosis", "biliary"}),
    },
    {
        "label": "renal",
        "tokens": frozenset({"renal", "kidney", "nephron", "glomerular",
                              "glomerulus", "tubular", "nephritic"}),
    },
]


def _tokenize_set(text: str) -> FrozenSet[str]:
    """Return a frozenset of lower-case alpha-numeric tokens from *text*."""
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def _apply_topic_guard(
    papers: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    """Remove papers whose title/abstract contain off-topic organism/tissue
    terms unless the query itself mentions those terms.

    Papers that are filtered out are excluded from the returned list.
    A ``topic_guard_filtered`` flag is set to ``True`` on removed papers so
    callers can inspect them (the list is still returned as a separate value by
    :func:`apply_topic_guard_split` if needed).

    Args:
        papers: Scored paper dicts (must already have ``title``/``abstract``).
        query: The effective search query string.

    Returns:
        Filtered list of papers that passed the guard.
    """
    query_tokens = _tokenize_set(query)
    kept: List[Dict[str, Any]] = []
    for paper in papers:
        text = f"{paper.get('title', '')} {paper.get('abstract', '')}".strip()
        paper_tokens = _tokenize_set(text)
        filtered = False
        for group in _TOPIC_GUARD_GROUPS:
            guard_tokens: FrozenSet[str] = group["tokens"]
            # Skip this guard group when the query explicitly references it
            if query_tokens & guard_tokens:
                continue
            if paper_tokens & guard_tokens:
                paper["topic_guard_filtered"] = True
                paper["topic_guard_label"] = group["label"]
                filtered = True
                # Log filtered paper tokens for guard-term learning
                _log_guard_filtered(paper, group["label"], paper_tokens)
                break
        if not filtered:
            kept.append(paper)
    return kept


def _log_guard_filtered(
    paper: Dict[str, Any],
    label: str,
    paper_tokens: FrozenSet[str],
) -> None:
    """Append a filtered paper's tokens to the guard false-positive log."""
    try:
        _GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
        write_header = not _GUARD_LOG.exists()
        # Only log tokens not in ANY guard group (potential new guard terms)
        all_guard_tokens: FrozenSet[str] = frozenset(
            t for g in _TOPIC_GUARD_GROUPS for t in g["tokens"]
        )
        novel_tokens = paper_tokens - all_guard_tokens - {"the", "and", "for", "with"}
        with open(_GUARD_LOG, "a", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["ts", "doi", "title", "guard_label", "unguarded_tokens"],
                delimiter="\t",
            )
            if write_header:
                w.writeheader()
            w.writerow({
                "ts": datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "doi": (paper.get("doi") or "")[:80],
                "title": (paper.get("title") or "")[:120],
                "guard_label": label,
                "unguarded_tokens": " ".join(sorted(novel_tokens)[:30]),
            })
    except Exception:
        pass


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


def apply_topic_guard(
    papers: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    """Public alias for :func:`_apply_topic_guard`.

    Call *after* scoring and *before* output to remove papers that mention
    off-topic organisms/tissues not referenced in the query.
    """
    return _apply_topic_guard(papers, query)


def score_paper(
    paper: Dict[str, Any],
    claim: str,
    hypothesis: str,
    *,
    embed_sim: float = -1.0,
) -> Dict[str, Any]:
    """Score a paper for claim/hypothesis relevance.

    embed_sim: pre-computed cosine similarity from nomic-embed-text, or -1.0
    when not available (falls back to lexical-only scoring).
    """
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".strip()

    claim_overlap = overlap_ratio(claim, text) if claim else 0.0
    hypothesis_overlap = overlap_ratio(hypothesis, text) if hypothesis else 0.0

    citations = paper.get("citations") or 0
    if isinstance(citations, str) and citations.isdigit():
        citations = int(citations)
    if not isinstance(citations, int):
        citations = 0

    # ① Citation velocity: blend absolute count with per-year rate
    _year_raw = paper.get("year") or 0
    try:
        _paper_year = int(str(_year_raw)[:4]) if _year_raw else 0
    except (ValueError, TypeError):
        _paper_year = 0
    _age = max(1, 2026 - _paper_year + 1) if 1900 <= _paper_year <= 2026 else 20
    _cite_abs = min(citations, 500) / 500.0
    _cite_vel = min(citations / _age, 50.0) / 50.0
    cite_component = 0.5 * _cite_abs + 0.5 * _cite_vel

    # ② Recency bonus (max +0.02)
    if _paper_year >= 2024:
        _recency = 1.0
    elif _paper_year >= 2021:
        _recency = 0.6
    elif _paper_year >= 2016:
        _recency = 0.3
    else:
        _recency = 0.0
    recency_bonus = 0.02 * _recency

    source = (paper.get("source") or "").strip().lower()
    source_weight = _SOURCE_WEIGHTS.get(source, 0.88)
    has_doi = bool((paper.get("doi") or "").strip())
    has_abstract = bool((paper.get("abstract") or "").strip())
    metadata_bonus = 0.03 * float(has_doi) + 0.04 * float(has_abstract)

    stage1_raw = (
        0.50 * claim_overlap
        + 0.20 * hypothesis_overlap
        + 0.20 * cite_component
        + 0.10 * source_weight
        + metadata_bonus
        + recency_bonus
    )
    stage1 = round(min(stage1_raw, 1.0), 4)

    s2 = _sentence_analysis(claim, hypothesis, paper.get("abstract") or "")

    if claim and has_abstract:
        lexical_ev = 0.40 * stage1 + 0.60 * s2["stage2_score"]
        if embed_sim >= 0.0:
            # Blend 15% semantic similarity, preserving stage1/stage2 ratio.
            evidence_score = round(min(0.85 * lexical_ev + 0.15 * embed_sim, 1.0), 4)
        else:
            evidence_score = round(min(lexical_ev, 1.0), 4)
    else:
        evidence_score = stage1
    
    paper["claim_overlap"] = round(claim_overlap, 4)
    paper["hypothesis_overlap"] = round(hypothesis_overlap, 4)
    paper["source_weight"] = round(source_weight, 4)
    paper["metadata_bonus"] = round(metadata_bonus, 4)
    paper["recency_bonus"] = round(recency_bonus, 4)
    paper["stage1_score"] = stage1
    paper["stage2_score"] = s2["stage2_score"]
    paper["support_score"] = s2["support_score"]
    paper["contradiction_score"] = s2["contradiction_score"]
    paper["best_support_sentence"] = s2["best_support_sentence"]
    paper["best_contradict_sentence"] = s2["best_contradict_sentence"]
    paper["hypothesis_sentence_overlap"] = s2["hypothesis_sentence_overlap"]
    if embed_sim >= 0.0:
        paper["embed_sim"] = round(embed_sim, 4)
    paper["evidence_score"] = evidence_score
    paper["evidence_label"] = classify_evidence_label(
        support_score=s2["support_score"],
        contradiction_score=s2["contradiction_score"],
        evidence_score=evidence_score,
        has_claim=bool(claim.strip()),
    )

    return paper


def batch_score_papers(
    papers: List[Dict[str, Any]],
    claim: str,
    hypothesis: str,
) -> List[Dict[str, Any]]:
    """Score all papers, blending in nomic-embed semantic similarity when Ollama is available.

    Embeddings are fetched in a single batch call [claim, abstract_0, abstract_1, …].
    If Ollama is unavailable the function falls back to pure lexical scoring.
    """
    embed_sims: List[float] = [-1.0] * len(papers)
    if claim:
        abstracts = [str(p.get("abstract") or "") for p in papers]
        texts = [claim] + abstracts
        try:
            vecs = embed_texts(texts)
            if vecs and len(vecs) == len(texts):
                claim_vec = vecs[0]
                for i, abs_vec in enumerate(vecs[1:]):
                    if abs_vec and abstracts[i]:
                        embed_sims[i] = cosine_sim(claim_vec, abs_vec)
        except Exception:
            pass

    return [
        score_paper(p, claim, hypothesis, embed_sim=embed_sims[i])
        for i, p in enumerate(papers)
    ]
