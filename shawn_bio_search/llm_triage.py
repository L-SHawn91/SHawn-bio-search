"""Optional Ollama-backed semantic triage for search candidates.

The deterministic search/scoring layer remains the source of truth. This module
adds an enrichment pass that can fail back to local heuristics, so search still
runs when Ollama Cloud, local Ollama, or the network is unavailable.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, MutableMapping, Sequence, Tuple

from .scoring import classify_evidence_label, _TOPIC_GUARD_GROUPS, _tokenize_set
from .text_utils import overlap_ratio


DEFAULT_FALLBACK_CHAIN = (
    "gpt-oss:120b-cloud,deepseek-v4-flash:cloud,kimi-k2.6:cloud,"
    "deepseek-v3.1:671b-cloud,qwen3-coder:480b-cloud,gpt-oss:20b-cloud,code"
)
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_NUM_PREDICT = int(os.getenv("SBS_LLM_NUM_PREDICT", "512"))
VALID_DIRECTIONS = {"support", "contradict", "mixed", "uncertain", "mention-only"}


def split_model_chain(model: str = "", fallback_chain: str = "") -> List[str]:
    """Return the effective high -> value -> local -> code fallback chain."""
    effective_model = (
        model.strip()
        or os.getenv("ZCM_LLM_MODEL", "").strip()
        or os.getenv("SHAWN_LLM_MODEL", "").strip()
        or os.getenv("ZCM_LLM_CLOUD", "").strip()
    )
    chain_text = (
        fallback_chain
        or os.getenv("ZCM_LLM_FALLBACK_CHAIN", "")
        or os.getenv("SHAWN_LLM_FALLBACK_CHAIN", "")
        or ""
    )
    candidates: List[str] = []
    if effective_model:
        candidates.append(effective_model)
    if chain_text.strip():
        candidates.extend(_split_csv(chain_text))
    elif not candidates:
        candidates.extend(_split_csv(DEFAULT_FALLBACK_CHAIN))

    deduped: List[str] = []
    seen = set()
    for candidate in candidates:
        normalized = _normalize_model_ref(candidate)
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)

    if "code" not in seen:
        deduped.append("code")
    return deduped


def triage_papers(
    papers: Sequence[MutableMapping[str, Any]],
    query: str,
    claim: str = "",
    hypothesis: str = "",
    *,
    enabled: bool = False,
    model: str = "",
    fallback_chain: str = "",
    limit: int = 12,
    timeout: float = 30.0,
    rerank: bool = False,
    ollama_host: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Enrich top candidates with semantic relevance fields.

    When ``enabled`` is false this returns copies of the input papers and a
    disabled metadata block. When enabled, only the top ``limit`` candidates are
    sent through the fallback chain. Remaining papers are kept unchanged.
    """
    output = [dict(p) for p in papers]
    chain = split_model_chain(model=model, fallback_chain=fallback_chain)
    metadata: Dict[str, Any] = {
        "enabled": bool(enabled),
        "model_chain": chain,
        "limit": max(0, int(limit or 0)),
        "rerank": bool(rerank),
        "counts": {},
        "warnings": [],
        "usage": {},
    }
    if not enabled or not output or metadata["limit"] <= 0:
        return output, metadata

    host = (ollama_host or os.getenv("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")
    disabled_models: set[str] = set()
    triage_count = min(metadata["limit"], len(output))

    for idx in range(triage_count):
        result = _triage_one_with_chain(
            paper=output[idx],
            query=query,
            claim=claim,
            hypothesis=hypothesis,
            chain=chain,
            disabled_models=disabled_models,
            timeout=timeout,
            ollama_host=host,
        )
        output[idx].update(result)
        used = str(result.get("llm_model_used") or "unknown")
        metadata["counts"][used] = int(metadata["counts"].get(used, 0)) + 1
        usage = result.get("llm_usage")
        if isinstance(usage, dict):
            _add_usage(metadata["usage"], used, usage)
        warning = result.get("llm_triage_warning")
        if warning and warning not in metadata["warnings"]:
            metadata["warnings"].append(warning)

    if rerank:
        triaged = output[:triage_count]
        rest = output[triage_count:]
        for paper in triaged:
            llm_score = _safe_float(paper.get("llm_relevance"))
            evidence_score = _safe_float(paper.get("evidence_score"))
            paper["llm_combined_score"] = round(0.65 * evidence_score + 0.35 * llm_score, 4)
        triaged.sort(key=lambda p: _safe_float(p.get("llm_combined_score")), reverse=True)
        output = triaged + rest

    return output, metadata


def code_triage_paper(
    paper: MutableMapping[str, Any],
    query: str,
    claim: str = "",
    hypothesis: str = "",
    *,
    warning: str = "",
) -> Dict[str, Any]:
    """Deterministic fallback fields matching the Ollama triage schema."""
    title = str(paper.get("title") or "")
    abstract = str(paper.get("abstract") or "")
    text = f"{title} {abstract}".strip()
    evidence_score = _safe_float(paper.get("evidence_score"))
    claim_overlap = _safe_float(paper.get("claim_overlap"))
    hypothesis_overlap = _safe_float(paper.get("hypothesis_overlap"))
    query_overlap = overlap_ratio(query, text) if query and text else 0.0

    # Topic guard: if paper is off-topic and query doesn't reference that topic,
    # override to mention-only before computing direction.
    query_tokens = _tokenize_set(query)
    paper_tokens = _tokenize_set(text)
    _offtopic_override = False
    for _grp in _TOPIC_GUARD_GROUPS:
        if not (query_tokens & _grp["tokens"]) and (paper_tokens & _grp["tokens"]):
            _offtopic_override = True
            break

    relevance = max(
        evidence_score,
        0.45 * claim_overlap + 0.25 * hypothesis_overlap + 0.30 * query_overlap,
    )
    if _offtopic_override:
        relevance = min(relevance, 0.10)
    relevance = round(_clamp(relevance), 4)

    support = _safe_float(paper.get("support_score"))
    contradiction = _safe_float(paper.get("contradiction_score"))
    if _offtopic_override:
        direction = "mention-only"
    else:
        direction = str(paper.get("evidence_label") or "").strip().lower()
    if direction not in VALID_DIRECTIONS:
        direction = classify_evidence_label(
            support_score=support,
            contradiction_score=contradiction,
            evidence_score=evidence_score,
            has_claim=bool(claim.strip()),
        )

    reason = _fallback_reason(paper, direction, query_overlap)
    risk = _fallback_risk(paper, relevance, direction)
    result = {
        "llm_relevance": relevance,
        "llm_direction": direction,
        "llm_reason": reason,
        "llm_risk": risk,
        "llm_model_used": "code",
        "llm_provider": "code",
    }
    if warning:
        result["llm_triage_warning"] = warning
    return result


def _triage_one_with_chain(
    *,
    paper: MutableMapping[str, Any],
    query: str,
    claim: str,
    hypothesis: str,
    chain: Sequence[str],
    disabled_models: set[str],
    timeout: float,
    ollama_host: str,
) -> Dict[str, Any]:
    errors: List[str] = []
    for model in chain:
        if model == "code":
            warning = "; ".join(errors[:2])
            return code_triage_paper(paper, query, claim, hypothesis, warning=warning)
        if model in disabled_models:
            continue
        try:
            payload = _call_ollama_model(
                model=model,
                query=query,
                claim=claim,
                hypothesis=hypothesis,
                paper=paper,
                timeout=timeout,
                ollama_host=ollama_host,
            )
            return _normalize_llm_result(payload, model)
        except Exception as exc:  # pragma: no cover - exact network failures vary.
            errors.append(f"{model} failed: {_short_error(exc)}")
            disabled_models.add(model)

    warning = "; ".join(errors[:2])
    return code_triage_paper(paper, query, claim, hypothesis, warning=warning)


def _call_ollama_model(
    *,
    model: str,
    query: str,
    claim: str,
    hypothesis: str,
    paper: MutableMapping[str, Any],
    timeout: float,
    ollama_host: str,
) -> Dict[str, Any]:
    # Build domain hint from query tokens to help LLM identify off-topic papers.
    _q_tokens = _tokenize_set(query)
    _domain_hint = ""
    _ENDO_TOKENS = frozenset({"endometrial","endometrium","endometriosis","uterine","uterus",
                               "implantation","receptivity","decidualization","rif","woi"})
    if _q_tokens & _ENDO_TOKENS:
        _domain_hint = (
            " The research domain is endometrial/uterine biology. "
            "Papers about liver, prostate, kidney, lung, brain, breast, plant, or "
            "other non-endometrial topics should be classified as 'mention-only'."
        )
    system = (
        "You triage biomedical literature search candidates. Return strict JSON only. "
        "Do not invent citations, accessions, or facts beyond the provided title/abstract."
        + _domain_hint
    )
    user = {
        "query": query,
        "claim": claim,
        "hypothesis": hypothesis,
        "candidate": {
            "title": paper.get("title") or "",
            "abstract": _truncate(str(paper.get("abstract") or ""), 3500),
            "year": paper.get("year") or "",
            "source": paper.get("source") or "",
            "doi": paper.get("doi") or "",
            "evidence_score": paper.get("evidence_score"),
            "support_score": paper.get("support_score"),
            "contradiction_score": paper.get("contradiction_score"),
        },
        "required_schema": {
            "relevance": "number 0..1",
            "direction": "support|contradict|mixed|uncertain|mention-only",
            "reason": "short evidence-grounded reason",
            "risk": "short limitation or manual-check note",
        },
    }
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "options": {"temperature": 0, "num_predict": _ollama_num_predict()},
    }
    think = _ollama_think_for_model(model)
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(
        f"{ollama_host}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(str(exc)) from exc

    outer = json.loads(raw)
    content = outer.get("message", {}).get("content", "")
    if not content:
        content = outer.get("response", "")
    payload = _parse_json_payload(content)
    payload["_ollama_usage"] = _ollama_usage_from_response(outer)
    return payload


def _normalize_llm_result(payload: Dict[str, Any], model: str) -> Dict[str, Any]:
    relevance = _clamp(_safe_float(payload.get("relevance")))
    direction = str(payload.get("direction") or "uncertain").strip().lower()
    if direction not in VALID_DIRECTIONS:
        direction = "uncertain"
    result = {
        "llm_relevance": round(relevance, 4),
        "llm_direction": direction,
        "llm_reason": _clean_text(payload.get("reason") or "", fallback="LLM semantic triage"),
        "llm_risk": _clean_text(payload.get("risk") or "", fallback="Manual verification recommended"),
        "llm_model_used": model,
        "llm_provider": "ollama",
    }
    usage = payload.get("_ollama_usage")
    if isinstance(usage, dict):
        result["llm_usage"] = usage
    return result


def _ollama_usage_from_response(response: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "prompt_eval_count",
        "eval_count",
        "total_duration",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
    )
    usage = {key: response.get(key) for key in keys if isinstance(response.get(key), (int, float))}
    if "prompt_eval_count" in usage or "eval_count" in usage:
        usage["total_tokens"] = int(usage.get("prompt_eval_count", 0) or 0) + int(usage.get("eval_count", 0) or 0)
    return usage


def _add_usage(target: Dict[str, Any], model: str, usage: Dict[str, Any]) -> None:
    bucket = target.setdefault(
        model,
        {
            "calls": 0,
            "prompt_eval_count": 0,
            "eval_count": 0,
            "total_tokens": 0,
            "total_duration": 0,
            "load_duration": 0,
            "prompt_eval_duration": 0,
            "eval_duration": 0,
        },
    )
    bucket["calls"] += 1
    for key in (
        "prompt_eval_count",
        "eval_count",
        "total_tokens",
        "total_duration",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
    ):
        if isinstance(usage.get(key), (int, float)):
            bucket[key] += usage[key]


def _parse_json_payload(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM triage response must be a JSON object")
    return data


def _ollama_think_for_model(model: str) -> Any:
    requested = _parse_ollama_think(os.getenv("SBS_LLM_THINK", "auto"))
    if requested != "auto":
        return requested

    name = (model or "").lower()
    if "gpt-oss" in name:
        return "low"
    if (
        "deepseek" in name
        or "kimi-k2.6" in name
        or "qwen3-coder" in name
        or name.startswith("qwen3")
        or ":qwen3" in name
    ):
        return False
    return None


def _parse_ollama_think(value: str) -> str | bool:
    raw = (value or "auto").strip().lower()
    if raw in {"", "auto"}:
        return "auto"
    if raw in {"true", "1", "yes", "on"}:
        return True
    if raw in {"false", "0", "no", "off", "none"}:
        return False
    if raw in {"low", "medium", "high"}:
        return raw
    return raw


def _ollama_num_predict() -> int:
    try:
        return int(os.getenv("SBS_LLM_NUM_PREDICT", str(DEFAULT_OLLAMA_NUM_PREDICT)))
    except ValueError:
        return DEFAULT_OLLAMA_NUM_PREDICT


def _split_csv(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize_model_ref(value: str) -> str:
    value = value.strip()
    lower = value.lower()
    if lower in {"code", "heuristic", "code-only", "none"}:
        return "code"
    if lower.startswith("ollama:"):
        return value.split(":", 1)[1].strip()
    return value


def _fallback_reason(paper: MutableMapping[str, Any], direction: str, query_overlap: float) -> str:
    support = str(paper.get("best_support_sentence") or "").strip()
    contradict = str(paper.get("best_contradict_sentence") or "").strip()
    if direction == "support" and support:
        return _truncate(support, 180)
    if direction == "contradict" and contradict:
        return _truncate(contradict, 180)
    title = str(paper.get("title") or "").strip()
    if query_overlap >= 0.12 and title:
        return _truncate(f"Query terms overlap with title/abstract: {title}", 180)
    if title:
        return _truncate(f"Candidate retained by deterministic search: {title}", 180)
    return "Candidate retained by deterministic search"


def _fallback_risk(paper: MutableMapping[str, Any], relevance: float, direction: str) -> str:
    if not str(paper.get("abstract") or "").strip():
        return "No abstract available; manual review required"
    if not str(paper.get("doi") or "").strip():
        return "No DOI in source metadata"
    if direction in {"uncertain", "mixed"}:
        return "Direction is not decisive"
    if relevance < 0.2:
        return "Low lexical relevance"
    return "Manual verification recommended"


def _clean_text(value: Any, *, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return fallback
    return _truncate(text, 220)


def _truncate(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def _short_error(exc: BaseException) -> str:
    return _truncate(str(exc).replace("\n", " "), 140)


def _safe_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
