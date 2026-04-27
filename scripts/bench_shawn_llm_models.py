#!/usr/bin/env python3
"""Benchmark SHawn search triage models on a fixed biomedical candidate set."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shawn_bio_search.llm_triage import DEFAULT_OLLAMA_NUM_PREDICT, triage_papers  # noqa: E402


DEFAULT_MODELS = [
    "gpt-oss:120b-cloud",
    "kimi-k2.6:cloud",
    "deepseek-v4-flash:cloud",
    "deepseek-v3.1:671b-cloud",
    "qwen3-coder:480b-cloud",
    "gpt-oss:20b-cloud",
    "qwen3:8b",
    "qwen2.5:14b",
    "code",
]

OPTION_PRESETS: Dict[str, Dict[str, Any]] = {
    "auto": {},
    "think-false-np512": {"SBS_LLM_THINK": "false", "SBS_LLM_NUM_PREDICT": "512"},
    "think-low-np512": {"SBS_LLM_THINK": "low", "SBS_LLM_NUM_PREDICT": "512"},
    "think-low-np768": {"SBS_LLM_THINK": "low", "SBS_LLM_NUM_PREDICT": "768"},
    "think-low-np1024": {"SBS_LLM_THINK": "low", "SBS_LLM_NUM_PREDICT": "1024"},
    "think-false-np768": {"SBS_LLM_THINK": "false", "SBS_LLM_NUM_PREDICT": "768"},
    "think-false-np1024": {"SBS_LLM_THINK": "false", "SBS_LLM_NUM_PREDICT": "1024"},
}


def fixture_papers() -> List[Dict[str, Any]]:
    return [
        {
            "id": "support_organoid",
            "title": "Endometrial organoids model uterine epithelial differentiation",
            "abstract": "Endometrial organoids preserve hormone-responsive epithelial differentiation and model uterine biology.",
            "doi": "10.1000/support",
            "evidence_score": 0.52,
            "claim_overlap": 0.34,
            "hypothesis_overlap": 0.20,
            "support_score": 0.31,
            "contradiction_score": 0.01,
            "evidence_label": "support",
            "best_support_sentence": "Endometrial organoids preserve hormone-responsive epithelial differentiation and model uterine biology.",
            "_expected_direction": "support",
        },
        {
            "id": "offtopic_liver",
            "title": "Liver organoids for drug toxicity screening",
            "abstract": "Hepatic organoids support drug toxicity assays and metabolism studies.",
            "doi": "10.1000/offtopic",
            "evidence_score": 0.20,
            "claim_overlap": 0.05,
            "hypothesis_overlap": 0.00,
            "support_score": 0.02,
            "contradiction_score": 0.00,
            "evidence_label": "mention-only",
            "_expected_direction": "mention-only",
        },
        {
            "id": "uncertain_fibrosis",
            "title": "Endometrial stromal fibrosis marker survey",
            "abstract": "",
            "doi": "",
            "evidence_score": 0.18,
            "claim_overlap": 0.16,
            "hypothesis_overlap": 0.10,
            "support_score": 0.05,
            "contradiction_score": 0.03,
            "evidence_label": "uncertain",
            "_expected_direction": "uncertain",
        },
    ]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark SHawn Ollama/code triage models")
    parser.add_argument("--model", action="append", help="Model to benchmark. Repeatable.")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--check-seconds", type=float, default=30.0)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--query", default="endometrial organoid uterine biology")
    parser.add_argument("--claim", default="endometrial organoids model uterine biology")
    parser.add_argument(
        "--option-preset",
        action="append",
        choices=sorted(OPTION_PRESETS),
        help="Temporarily override SBS_LLM_* options for each model. Repeatable.",
    )
    return parser.parse_args(argv)


def direction_ok(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    if expected == "mention-only" and actual in {"mention-only", "uncertain"}:
        return True
    return False


def benchmark_model(
    model: str,
    query: str,
    claim: str,
    timeout: float,
    option_preset: str = "auto",
) -> Dict[str, Any]:
    papers = fixture_papers()
    fallback_chain = "code" if model == "code" else f"{model},code"
    env_backup = {key: os.environ.get(key) for key in ("SBS_LLM_THINK", "SBS_LLM_NUM_PREDICT")}
    for key, value in OPTION_PRESETS.get(option_preset, {}).items():
        os.environ[key] = str(value)
    start = time.perf_counter()
    try:
        out, meta = triage_papers(
            papers,
            query=query,
            claim=claim,
            enabled=True,
            model=model,
            fallback_chain=fallback_chain,
            limit=len(papers),
            timeout=timeout,
            rerank=False,
        )
    finally:
        for key, old_value in env_backup.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
    elapsed = time.perf_counter() - start

    rows: List[Dict[str, Any]] = []
    direction_hits = 0
    for paper in out:
        expected = str(paper.get("_expected_direction") or "")
        actual = str(paper.get("llm_direction") or "")
        ok = direction_ok(actual, expected)
        direction_hits += int(ok)
        rows.append(
            {
                "id": paper.get("id"),
                "expected_direction": expected,
                "llm_direction": actual,
                "direction_ok": ok,
                "llm_relevance": paper.get("llm_relevance"),
                "llm_model_used": paper.get("llm_model_used"),
                "llm_provider": paper.get("llm_provider"),
                "llm_reason": paper.get("llm_reason"),
                "llm_risk": paper.get("llm_risk"),
                "llm_usage": paper.get("llm_usage"),
                "warning": paper.get("llm_triage_warning", ""),
            }
        )

    support_score = float(rows[0].get("llm_relevance") or 0.0)
    off_topic_score = float(rows[1].get("llm_relevance") or 0.0)
    uncertain_score = float(rows[2].get("llm_relevance") or 0.0)
    separation = support_score - off_topic_score
    fallback_count = sum(1 for row in rows if row.get("llm_model_used") == "code" and model != "code")

    return {
        "model": model,
        "option_preset": option_preset,
        "elapsed_sec": round(elapsed, 3),
        "timeout_sec": timeout,
        "meta": meta,
        "direction_accuracy": round(direction_hits / max(1, len(rows)), 3),
        "support_relevance": support_score,
        "offtopic_relevance": off_topic_score,
        "uncertain_relevance": uncertain_score,
        "support_minus_offtopic": round(separation, 4),
        "fallback_count": fallback_count,
        "rows": rows,
    }


def write_markdown(records: List[Dict[str, Any]], path: Path) -> None:
    lines = [
        "# SHawn LLM Model Benchmark",
        "",
        f"- generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "- task: fixed biomedical search triage fixture",
        "",
        "| Model | Preset | Options | Elapsed s | Sec/item | Tokens/item | ETA 100 | ETA 500 | ETA 1000 | Direction acc | Separation | Fallbacks | Used models |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for rec in records:
        counts = rec.get("meta", {}).get("counts", {})
        used = ", ".join(f"{k}:{v}" for k, v in counts.items())
        item_count = max(1, len(rec.get("rows") or []))
        sec_per_item = float(rec["elapsed_sec"]) / item_count
        lines.append(
            "| {model} | {preset} | {options} | {elapsed:.3f} | {sec_per_item:.3f} | {tokens_per_item:.1f} | {eta100} | {eta500} | {eta1000} | {acc:.3f} | {sep:.2f} | {fallbacks} | {used} |".format(
                model=rec["model"],
                preset=rec.get("option_preset", "auto"),
                options=_option_summary(str(rec["model"]), float(rec.get("timeout_sec") or 0), str(rec.get("option_preset", "auto"))),
                elapsed=float(rec["elapsed_sec"]),
                sec_per_item=sec_per_item,
                tokens_per_item=_tokens_per_item(rec),
                eta100=_format_eta(sec_per_item * 100),
                eta500=_format_eta(sec_per_item * 500),
                eta1000=_format_eta(sec_per_item * 1000),
                acc=float(rec["direction_accuracy"]),
                sep=float(rec["support_minus_offtopic"]),
                fallbacks=int(rec["fallback_count"]),
                used=used or "-",
            )
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("- Direction accuracy is measured against a tiny fixed fixture, not a publication-grade golden set.")
    lines.append("- Separation is support relevance minus off-topic relevance; higher is better for triage.")
    lines.append("- Options are the effective triage options: `format=json`, `temperature=0`, fixed output budget, and model-specific `think` setting.")
    lines.append("- Tokens/item uses Ollama response counts: prompt_eval_count + eval_count, when the model returns them.")
    lines.append("- ETA assumes the current sequential triage implementation; future parallelization changes this.")
    lines.append("- Fallbacks indicate the requested model did not finish within timeout and code fallback handled the row.")
    path.write_text("\n".join(lines), encoding="utf-8")


def _format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def _tokens_per_item(record: Dict[str, Any]) -> float:
    usage = (record.get("meta") or {}).get("usage") or {}
    total_tokens = 0
    calls = 0
    for bucket in usage.values():
        if isinstance(bucket, dict):
            total_tokens += int(bucket.get("total_tokens") or 0)
            calls += int(bucket.get("calls") or 0)
    return total_tokens / calls if calls else 0.0


def _option_summary(model: str, timeout: float, option_preset: str = "auto") -> str:
    name = (model or "").lower()
    if model == "code":
        return "heuristic"
    preset = OPTION_PRESETS.get(option_preset, {})
    if "SBS_LLM_THINK" in preset:
        think = str(preset["SBS_LLM_THINK"])
    elif "gpt-oss" in name:
        think = "low"
    elif "deepseek" in name or "kimi-k2.6" in name or "qwen3-coder" in name or name.startswith("qwen3") or ":qwen3" in name:
        think = "false"
    else:
        think = "auto"
    num_predict = str(preset.get("SBS_LLM_NUM_PREDICT", DEFAULT_OLLAMA_NUM_PREDICT))
    timeout_text = "none" if timeout <= 0 else f"{timeout:.0f}s"
    return f"json,temp0,np{num_predict},think={think},timeout={timeout_text}"


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    models = args.model or DEFAULT_MODELS
    option_presets = args.option_preset or ["auto"]
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else REPO_ROOT / "outputs" / "llm_model_bench" / datetime.now().strftime("%Y%m%d_%H%M%S")
    if not out_dir.is_absolute():
        out_dir = (REPO_ROOT / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for model in models:
        for option_preset in option_presets:
            print(f"benchmarking: {model} preset={option_preset}", flush=True)
            start = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(benchmark_model, model, args.query, args.claim, args.timeout, option_preset)
                while True:
                    try:
                        records.append(future.result(timeout=max(1.0, args.check_seconds)))
                        break
                    except concurrent.futures.TimeoutError:
                        elapsed = time.perf_counter() - start
                        print(f"benchmark_check: {model} preset={option_preset} still running after {elapsed:.1f}s", flush=True)

    json_path = out_dir / "MODEL_BENCHMARK.json"
    md_path = out_dir / "MODEL_BENCHMARK.md"
    json_path.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(records, md_path)
    print(f"saved: {json_path}")
    print(f"saved: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
