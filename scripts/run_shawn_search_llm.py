#!/usr/bin/env python3
"""Fixed SHawn high-performance search runner.

This is the stable CLI entry point Codex/Claude can call instead of assembling
model, fallback, rerank, and output flags by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH_BUNDLE = Path(__file__).with_name("search_bundle.py")


@dataclass(frozen=True)
class QualityProfile:
    name: str
    model: str
    fallback_chain: str
    llm_limit: int
    max_papers_per_source: int
    max_datasets_per_source: int
    fast: bool
    rerank: bool


QUALITY_PROFILES: Dict[str, QualityProfile] = {
    "max": QualityProfile(
        name="max",
        model="gpt-oss:120b-cloud",
        fallback_chain="gpt-oss:120b-cloud,deepseek-v4-flash:cloud,kimi-k2.6:cloud,deepseek-v3.1:671b-cloud,qwen3-coder:480b-cloud,gpt-oss:20b-cloud,code",
        llm_limit=50,
        max_papers_per_source=8,
        max_datasets_per_source=5,
        fast=True,
        rerank=True,
    ),
    "deep": QualityProfile(
        name="deep",
        model="deepseek-v4-flash:cloud",
        fallback_chain="deepseek-v4-flash:cloud,gpt-oss:120b-cloud,deepseek-v3.1:671b-cloud,kimi-k2.6:cloud,gpt-oss:20b-cloud,code",
        llm_limit=30,
        max_papers_per_source=8,
        max_datasets_per_source=5,
        fast=True,
        rerank=True,
    ),
    "agent": QualityProfile(
        name="agent",
        model="kimi-k2.6:cloud",
        fallback_chain="kimi-k2.6:cloud,qwen3-coder:480b-cloud,gpt-oss:120b-cloud,deepseek-v3.1:671b-cloud,gpt-oss:20b-cloud,code",
        llm_limit=30,
        max_papers_per_source=8,
        max_datasets_per_source=5,
        fast=True,
        rerank=True,
    ),
    "fast": QualityProfile(
        name="fast",
        model="gpt-oss:20b-cloud",
        fallback_chain="gpt-oss:20b-cloud,code",
        llm_limit=30,
        max_papers_per_source=8,
        max_datasets_per_source=5,
        fast=True,
        rerank=True,
    ),
    "local": QualityProfile(
        name="local",
        model="qwen3:8b",
        fallback_chain="qwen3:8b,qwen2.5:14b,code",
        llm_limit=6,
        max_papers_per_source=8,
        max_datasets_per_source=5,
        fast=True,
        rerank=True,
    ),
    "code": QualityProfile(
        name="code",
        model="code",
        fallback_chain="code",
        llm_limit=12,
        max_papers_per_source=8,
        max_datasets_per_source=5,
        fast=True,
        rerank=True,
    ),
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SHawn-bio-search with fixed Ollama/code fallback profiles"
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--claim", default="")
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--organism", default="")
    parser.add_argument("--assay", default="")
    parser.add_argument("--quality", choices=sorted(QUALITY_PROFILES), default="max")
    parser.add_argument("--out", default="", help="Bundle JSON path. Defaults to outputs/llm_search/<timestamp>/bundle.json")
    parser.add_argument("--export-dual-engine-dir", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--zotero-root", default="")
    parser.add_argument("--unpaywall-email", default=os.getenv("UNPAYWALL_EMAIL", ""))
    parser.add_argument("--include-datasets", action="store_true", help="Run dataset search in fast retrieval mode")
    parser.add_argument("--full", action="store_true", help="Use full source retrieval instead of fast PubMed/EuropePMC/OpenAlex mode")
    parser.add_argument("--legacy-evidence", action="store_true")
    parser.add_argument("--expand-query", action="store_true")
    parser.add_argument("--project-mode", default="")
    parser.add_argument("--max-papers-per-source", type=int, default=0, help="Override quality profile paper limit")
    parser.add_argument("--max-datasets-per-source", type=int, default=0, help="Override quality profile dataset limit")
    parser.add_argument("--llm-limit", type=int, default=0, help="Override quality profile triage limit")
    parser.add_argument("--llm-timeout", type=float, default=180.0)
    parser.add_argument("--check-seconds", type=float, default=30.0, help="Progress heartbeat interval while the child pipeline is still running")
    parser.add_argument("--llm-model", default="", help="Override quality profile preferred model")
    parser.add_argument("--llm-fallback-chain", default="", help="Override quality profile fallback chain")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print command and metadata without executing")
    parser.add_argument("--print-command", action="store_true", help="Print shell-escaped search_bundle command")
    return parser.parse_args(argv)


def resolve_profile(args: argparse.Namespace) -> QualityProfile:
    base = QUALITY_PROFILES[args.quality]
    return QualityProfile(
        name=base.name,
        model=args.llm_model.strip() or base.model,
        fallback_chain=args.llm_fallback_chain.strip() or base.fallback_chain,
        llm_limit=args.llm_limit if args.llm_limit > 0 else base.llm_limit,
        max_papers_per_source=(
            args.max_papers_per_source
            if args.max_papers_per_source > 0
            else base.max_papers_per_source
        ),
        max_datasets_per_source=(
            args.max_datasets_per_source
            if args.max_datasets_per_source > 0
            else base.max_datasets_per_source
        ),
        fast=False if args.full else base.fast,
        rerank=False if args.no_rerank else base.rerank,
    )


def default_out_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "outputs" / "llm_search" / stamp / "bundle.json"


def build_search_command(args: argparse.Namespace, profile: QualityProfile, out_path: Path) -> List[str]:
    cmd = [
        sys.executable,
        str(SEARCH_BUNDLE),
        "--query",
        args.query,
        "--max-papers-per-source",
        str(profile.max_papers_per_source),
        "--max-datasets-per-source",
        str(profile.max_datasets_per_source),
        "--llm-triage",
        "--llm-model",
        profile.model,
        "--llm-fallback-chain",
        profile.fallback_chain,
        "--llm-limit",
        str(profile.llm_limit),
        "--llm-timeout",
        str(args.llm_timeout),
        "--out",
        str(out_path),
    ]
    optional_pairs = [
        ("--claim", args.claim),
        ("--hypothesis", args.hypothesis),
        ("--organism", args.organism),
        ("--assay", args.assay),
        ("--project", args.project),
        ("--zotero-root", args.zotero_root),
        ("--unpaywall-email", args.unpaywall_email),
        ("--project-mode", args.project_mode),
        ("--export-dual-engine-dir", args.export_dual_engine_dir),
    ]
    for flag, value in optional_pairs:
        if value:
            cmd.extend([flag, value])
    if profile.fast:
        cmd.append("--fast")
    if args.include_datasets:
        cmd.append("--include-datasets")
    if args.expand_query:
        cmd.append("--expand-query")
    if args.legacy_evidence:
        cmd.append("--legacy-evidence")
    if profile.rerank:
        cmd.append("--llm-rerank")
    return cmd


def summarize_bundle(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"parse_error": str(exc)}

    papers = data.get("papers") or {}
    datasets = data.get("datasets") or {}
    paper_rows = papers.get("papers") or []
    top_models: Dict[str, int] = {}
    for paper in paper_rows:
        model = paper.get("llm_model_used")
        if model:
            top_models[str(model)] = top_models.get(str(model), 0) + 1

    return {
        "paper_count": papers.get("count", len(paper_rows)),
        "dataset_count": datasets.get("count", len(datasets.get("datasets") or [])),
        "llm_triage": papers.get("llm_triage") or {},
        "llm_model_counts": top_models,
        "paper_warnings": papers.get("warnings", []),
        "dataset_warnings": datasets.get("warnings", []),
    }


def write_run_meta(
    *,
    out_path: Path,
    profile: QualityProfile,
    cmd: List[str],
    elapsed_sec: float,
    return_code: int,
    summary: Dict[str, Any],
) -> Path:
    meta_path = out_path.with_name("RUN_META.json")
    meta = {
        "runner": "run_shawn_search_llm.py",
        "quality": profile.name,
        "model": profile.model,
        "fallback_chain": profile.fallback_chain,
        "llm_limit": profile.llm_limit,
        "max_papers_per_source": profile.max_papers_per_source,
        "max_datasets_per_source": profile.max_datasets_per_source,
        "fast": profile.fast,
        "rerank": profile.rerank,
        "elapsed_sec": round(elapsed_sec, 3),
        "return_code": return_code,
        "bundle": str(out_path),
        "command": cmd,
        "summary": summary,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    profile = resolve_profile(args)
    out_path = Path(args.out).expanduser() if args.out else default_out_path()
    if not out_path.is_absolute():
        out_path = (REPO_ROOT / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_search_command(args, profile, out_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    command_text = shlex.join(cmd)
    if args.print_command or args.dry_run:
        print(command_text)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "quality": profile.name,
                    "model": profile.model,
                    "fallback_chain": profile.fallback_chain,
                    "out": str(out_path),
                    "fast": profile.fast,
                    "rerank": profile.rerank,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    start = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), env=env, text=True)
    check_seconds = max(1.0, float(args.check_seconds or 30.0))
    next_check = check_seconds
    while proc.poll() is None:
        time.sleep(min(check_seconds, 5.0))
        elapsed_now = time.perf_counter() - start
        if elapsed_now >= next_check:
            print(f"runner_check: still running after {elapsed_now:.1f}s", flush=True)
            next_check += check_seconds
    elapsed = time.perf_counter() - start
    summary = summarize_bundle(out_path) if out_path.exists() else {"missing_bundle": str(out_path)}
    meta_path = write_run_meta(
        out_path=out_path,
        profile=profile,
        cmd=cmd,
        elapsed_sec=elapsed,
        return_code=proc.returncode,
        summary=summary,
    )

    print(f"runner_quality: {profile.name}")
    print(f"runner_model: {profile.model}")
    print(f"runner_fallback_chain: {profile.fallback_chain}")
    print(f"runner_elapsed_sec: {elapsed:.3f}")
    print(f"bundle: {out_path}")
    print(f"run_meta: {meta_path}")
    if summary:
        print("summary: " + json.dumps(summary, ensure_ascii=False))
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
