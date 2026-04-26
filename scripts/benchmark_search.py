#!/usr/bin/env python3
"""Benchmark SHawn-bio-search fast vs default modes.

Usage:
  python3 scripts/benchmark_search.py \
    --query "endometrial organoid" \
    --query "autophagy uterine" \
    --repeat 1 \
    --max-papers-per-source 8 \
    --max-datasets-per-source 0 \
    --out output/shawn-bio-benchmark.jsonl
"""

import argparse
import json
import time
from pathlib import Path
from subprocess import PIPE, CalledProcessError, run
from typing import Any, Dict, List, Tuple


def _run_command(cmd: List[str], env=None) -> Tuple[float, str, str]:
    start = time.perf_counter()
    completed = run(cmd, stdout=PIPE, stderr=PIPE, text=True, check=False)
    elapsed = time.perf_counter() - start
    return elapsed, completed.stdout, completed.stderr, completed.returncode


def _extract_count(bundle: Dict[str, Any], key: str) -> int:
    try:
        return int(bundle.get(key, {}).get("count", 0))
    except Exception:
        return 0


def _main() -> int:
    p = argparse.ArgumentParser(description="Benchmark SHawn-bio-search modes")
    p.add_argument("--query", action="append", required=True, help="One or more query strings")
    p.add_argument("--claim", default="")
    p.add_argument("--hypothesis", default="")
    p.add_argument("--organism", default="")
    p.add_argument("--assay", default="")
    p.add_argument("--max-papers-per-source", type=int, default=8)
    p.add_argument("--max-datasets-per-source", type=int, default=0)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--out", default="output/shawn-bio-benchmark.jsonl")
    p.add_argument("--bundle-dir", default="/tmp")
    args = p.parse_args()

    base_cmd = [
        "python3",
        str(Path(__file__).with_name("search_bundle.py")),
        "--max-papers-per-source",
        str(args.max_papers_per_source),
        "--max-datasets-per-source",
        str(args.max_datasets_per_source),
    ]
    if args.claim:
        base_cmd += ["--claim", args.claim]
    if args.hypothesis:
        base_cmd += ["--hypothesis", args.hypothesis]
    if args.organism:
        base_cmd += ["--organism", args.organism]
    if args.assay:
        base_cmd += ["--assay", args.assay]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []
    for q in args.query:
        for mode in ("fast", "full"):
            for i in range(args.repeat):
                bundle = Path(args.bundle_dir) / f"tmp_bench_{mode}_{abs(hash((q,i))) % 1000000}.json"
                cmd = base_cmd + ["--query", q, "--out", str(bundle)]
                if mode == "fast":
                    cmd.append("--fast")

                # fast mode default skips datasets already unless explicitly forced
                elapsed, out, err, rc = _run_command(cmd)

                rec: Dict[str, Any] = {
                    "mode": mode,
                    "query": q,
                    "repeat": i + 1,
                    "elapsed_sec": round(elapsed, 3),
                    "return_code": rc,
                    "stdout_tail": (out or "").strip().split("\n")[-3:],
                    "stderr_tail": (err or "").strip().split("\n")[-3:],
                }

                if rc != 0:
                    rec["status"] = "failed"
                    rec["error"] = rec["stderr_tail"]
                    records.append(rec)
                    continue

                try:
                    data = json.loads(bundle.read_text(encoding="utf-8"))
                except Exception as exc:
                    rec["status"] = "parse_error"
                    rec["error"] = str(exc)
                    records.append(rec)
                    continue

                papers = data.get("papers", {})
                datasets = data.get("datasets", {})
                rec.update(
                    {
                        "status": "ok",
                        "paper_count": _extract_count(data, "papers"),
                        "dataset_count": _extract_count(data, "datasets"),
                        "paper_warnings": papers.get("warnings", []),
                        "dataset_warnings": datasets.get("warnings", []),
                    }
                )

                records.append(rec)

    # newline-delimited for easy grep + jq
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # summary table
    print(f"saved benchmark: {out_path}")
    summary = {}
    for r in records:
        if r["status"] != "ok":
            continue
        mode = r["mode"]
        key = (r["query"], mode)
        summary.setdefault(key, []).append(r["elapsed_sec"])

    if summary:
        print("\n=== mode summary (avg sec) ===")
        for (query, mode), vals in sorted(summary.items()):
            avg = sum(vals) / len(vals)
            print(f"{mode:5} | {query[:48]:48} | avg={avg:.3f}s over {len(vals)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
