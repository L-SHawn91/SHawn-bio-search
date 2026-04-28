#!/usr/bin/env python3
"""Endometrial gold-set LLM triage benchmark (43 papers: 37 support + 6 off-topic).

Metrics
-------
acc (lenient)  : support paper counts as correct if direction ∈ {support, mixed, uncertain}
strict         : exact direction match required
offtopic_recall: off-topic papers correctly classified as mention-only
support_recall : support papers correctly classified (lenient)

Usage
-----
    python3 scripts/bench_endometrial_gold.py --model code
    python3 scripts/bench_endometrial_gold.py --model gpt-oss:120b-cloud
    python3 scripts/bench_endometrial_gold.py  # runs code + default cloud chain
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shawn_bio_search.llm_triage import triage_papers  # noqa: E402
from shawn_bio_search.scoring import score_paper  # noqa: E402


QUERY = "endometrial cancer organoid uterine biology implantation receptivity"
CLAIM = "endometrial organoids model uterine function and are relevant to endometrial cancer biology"


def gold_set() -> List[Dict[str, Any]]:
    """43-paper endometrial gold set: 37 support + 6 off-topic."""

    def s(id_, title, abstract, ev=0.45, sup=0.28, contra=0.01):
        return {
            "id": id_, "title": title, "abstract": abstract,
            "doi": f"10.1000/{id_}", "source": "pubmed",
            "evidence_score": ev, "claim_overlap": 0.30,
            "hypothesis_overlap": 0.15, "support_score": sup,
            "contradiction_score": contra,
            "best_support_sentence": abstract[:200] if abstract else title,
            "_expected_direction": "support",
        }

    def o(id_, title, abstract):
        return {
            "id": id_, "title": title, "abstract": abstract,
            "doi": f"10.1000/{id_}", "source": "pubmed",
            "evidence_score": 0.08, "claim_overlap": 0.04,
            "hypothesis_overlap": 0.00, "support_score": 0.02,
            "contradiction_score": 0.00,
            "_expected_direction": "mention-only",
        }

    return [
        # ── Endometrial cancer ──────────────────────────────────────────────
        s("ec01", "POLE mutations in endometrial carcinoma",
          "POLE ultramutated endometrial carcinomas show improved prognosis and distinct immunological features."),
        s("ec02", "MMR deficiency and microsatellite instability in endometrial cancer",
          "Mismatch repair deficiency underlies microsatellite instability in a large proportion of endometrial carcinomas."),
        s("ec03", "PIK3CA mutation landscape in endometrial tumors",
          "PIK3CA mutations are among the most frequent alterations in endometrial adenocarcinoma."),
        s("ec04", "CTNNB1 mutations in low-grade endometrial carcinoma",
          "Beta-catenin pathway activation through CTNNB1 mutations is common in endometrioid endometrial cancer."),
        s("ec05", "PD-L1 expression and immunotherapy response in endometrial cancer",
          "PD-L1 positive endometrial tumors show increased response to immune checkpoint blockade."),
        s("ec06", "TCGA molecular classification of uterine corpus endometrial carcinoma",
          "Four molecular subtypes of endometrial carcinoma are defined by POLE, MSI, CNL, and CNH status."),
        s("ec07", "Endometrial carcinoma organoids preserve molecular heterogeneity",
          "Patient-derived endometrial cancer organoids recapitulate the molecular diversity of the primary tumor."),
        s("ec08", "TP53 aberrations in serous endometrial carcinoma",
          "Uterine serous carcinoma is characterized by frequent TP53 mutations and high copy number alterations."),
        s("ec09", "ARID1A loss in endometrial endometrioid carcinoma",
          "ARID1A mutations are a frequent early event in endometrial carcinogenesis."),
        s("ec10", "Hormone receptor expression and prognosis in endometrial cancer",
          "Estrogen and progesterone receptor positivity is associated with favorable outcomes in endometrial cancer."),
        # ── Endometriosis ───────────────────────────────────────────────────
        s("endo01", "Single-cell transcriptomics of eutopic and ectopic endometrium in endometriosis",
          "Single-cell RNA sequencing reveals distinct stromal and epithelial cell populations in endometriosis lesions."),
        s("endo02", "Epigenetic dysregulation in endometriosis stromal cells",
          "Aberrant DNA methylation and histone modifications drive endometriosis-associated gene expression changes."),
        s("endo03", "Endometriosis organoid model for drug screening",
          "Three-dimensional endometriosis organoids recapitulate lesion biology and enable high-throughput drug testing."),
        s("endo04", "Immune microenvironment alterations in peritoneal endometriosis",
          "Increased peritoneal macrophages and regulatory T cells create an immunosuppressive environment in endometriosis."),
        s("endo05", "Progesterone resistance mechanism in endometriosis",
          "Reduced progesterone receptor B expression underlies progesterone resistance in endometriotic stromal cells."),
        s("endo06", "Nerve fiber density and pain in endometriosis",
          "Increased innervation of endometriosis lesions correlates with pelvic pain severity."),
        # ── RIF / implantation failure ──────────────────────────────────────
        s("rif01", "Endometrial transcriptome in recurrent implantation failure",
          "RNA sequencing of endometrium from RIF patients reveals dysregulated receptivity genes."),
        s("rif02", "Pinopode formation defects in implantation failure",
          "Reduced pinopode density during the window of implantation is associated with recurrent IVF failure."),
        s("rif03", "Uterine natural killer cell abnormalities in RIF",
          "Abnormal uterine NK cell populations are found in women with recurrent implantation failure."),
        s("rif04", "Microbiome dysbiosis and implantation failure",
          "Non-Lactobacillus-dominant endometrial microbiome is associated with reduced IVF success rates."),
        s("rif05", "ERA test and personalized embryo transfer in RIF",
          "Endometrial receptivity analysis-guided embryo transfer improves implantation rates in RIF patients."),
        s("rif06", "Integrin expression and endometrial receptivity",
          "alphavbeta3 integrin expression during the window of implantation is diminished in RIF patients."),
        # ── WOI / decidualization ───────────────────────────────────────────
        s("woi01", "Transcriptomic signature of the window of implantation",
          "Temporal gene expression profiling identifies a precise molecular window for endometrial receptivity."),
        s("woi02", "Decidualization markers in endometrial stromal cells",
          "IGFBP1 and prolactin secretion are hallmarks of in vitro decidualization of human endometrial stromal cells."),
        s("woi03", "HOXA10 expression during the WOI",
          "HOXA10 is upregulated in the endometrium during the window of implantation and regulates receptivity."),
        s("woi04", "Progesterone-driven decidualization transcriptome",
          "Progesterone orchestrates decidualization through PGR-mediated activation of FOXO1 and KLF transcription factors."),
        s("woi05", "Endometrial organoid model of decidualization",
          "Endometrial organoids recapitulate hormone-induced decidualization and model the implantation window."),
        s("woi06", "LIF signaling in endometrial receptivity",
          "Leukemia inhibitory factor is a critical cytokine for uterine receptivity and embryo implantation."),
        # ── Organoids / culture models ──────────────────────────────────────
        s("org01", "Long-term endometrial organoid culture",
          "Long-term, hormone-responsive endometrial organoid cultures model glandular epithelium renewal."),
        s("org02", "Endometrial assembloids for implantation research",
          "Endometrial assembloids combining epithelial and stromal organoids recapitulate embryo attachment."),
        s("org03", "Patient-derived endometrial organoids for personalized medicine",
          "Endometrial organoids derived from patients with uterine pathology preserve disease-specific features."),
        s("org04", "Single-cell atlas of human endometrial organoids",
          "Single-cell RNA-seq of endometrial organoids resolves glandular cell heterogeneity and hormone response."),
        # ── Stem cells / regeneration ───────────────────────────────────────
        s("stem01", "Endometrial stem/progenitor cells and regeneration",
          "CD44+ and SSEA-1+ stem cell populations contribute to endometrial regeneration after menstruation."),
        s("stem02", "Asherman syndrome and endometrial stem cell depletion",
          "Intrauterine adhesions in Asherman syndrome correlate with reduced endometrial stem cell populations."),
        # ── Stromal / immune ────────────────────────────────────────────────
        s("strom01", "Endometrial stromal cell invasion mechanisms",
          "Matrix metalloproteinase activity mediates endometrial stromal invasion in endometriosis."),
        s("strom02", "Macrophage polarization in endometrial pathology",
          "M2-polarized macrophages are enriched in endometriosis and impaired endometrial receptivity."),
        s("strom03", "IL-6 signaling in endometrial stromal decidualization",
          "Interleukin-6 promotes decidualization of endometrial stromal cells via JAK-STAT3 pathway."),

        # ── Off-topic (6) ───────────────────────────────────────────────────
        o("ot_liver", "Hepatocyte organoids for liver disease modeling",
          "Liver organoids derived from hepatocytes model biliary cirrhosis and hepatic drug metabolism."),
        o("ot_prostate", "Androgen receptor signaling in prostate carcinoma",
          "Prostatic androgen receptor drives prostate cancer proliferation and castration resistance."),
        o("ot_plant", "Arabidopsis thaliana response to phytohormone treatment",
          "Phytohormone signaling in plant seedlings regulates photosynthesis and chloroplast development."),
        o("ot_kidney", "Renal tubular organoids model glomerular disease",
          "Kidney organoids recapitulate nephron structure and model renal tubular injury."),
        o("ot_cervical", "HPV integration and cervical carcinoma progression",
          "Human papillomavirus integration into cervical epithelium drives cervical cancer development."),
        o("ot_lung", "KRAS mutations in non-small-cell lung carcinoma",
          "KRAS-mutant lung adenocarcinoma shows distinct therapeutic vulnerabilities."),
    ]


def run_bench(
    model: str,
    timeout: float = 90.0,
    query: str = QUERY,
    claim: str = CLAIM,
) -> Dict[str, Any]:
    raw_papers = gold_set()
    n_support = sum(1 for p in raw_papers if p["_expected_direction"] == "support")
    n_offtopic = sum(1 for p in raw_papers if p["_expected_direction"] == "mention-only")

    # Re-score from title+abstract only — strip pre-set scores so the code
    # heuristic must classify from scratch (no cheating via evidence_label or
    # hardcoded support_score).
    _STRIP = {"evidence_score", "support_score", "contradiction_score",
              "claim_overlap", "hypothesis_overlap", "evidence_label",
              "best_support_sentence"}
    papers = []
    for p in raw_papers:
        stripped = {k: v for k, v in p.items() if k not in _STRIP}
        scored = score_paper(stripped, claim=claim, hypothesis="")
        scored["_expected_direction"] = p["_expected_direction"]
        papers.append(scored)

    fallback_chain = "code" if model == "code" else f"{model},code"
    os.environ["SBS_LLM_THINK"] = "false"
    os.environ["SBS_LLM_NUM_PREDICT"] = "512"

    t0 = time.perf_counter()
    out, meta = triage_papers(
        papers, query=query, claim=claim,
        enabled=True, model=model, fallback_chain=fallback_chain,
        limit=len(papers), timeout=timeout, rerank=False,
    )
    elapsed = time.perf_counter() - t0

    acc_hits = strict_hits = offtopic_hits = support_hits = 0
    for paper in out:
        exp = paper["_expected_direction"]
        act = str(paper.get("llm_direction") or "")
        if exp == "support":
            if act in {"support", "mixed", "uncertain"}:
                acc_hits += 1
            if act == "support":
                strict_hits += 1
                support_hits += 1
        elif exp == "mention-only":
            if act == "mention-only":
                acc_hits += 1
                strict_hits += 1
                offtopic_hits += 1

    n = len(papers)
    return {
        "model": model,
        "n": n, "n_support": n_support, "n_offtopic": n_offtopic,
        "acc":     round(acc_hits / n, 3),
        "strict":  round(strict_hits / n, 3),
        "offtopic_recall": f"{offtopic_hits}/{n_offtopic}",
        "support_recall":  f"{support_hits}/{n_support}",
        "elapsed": round(elapsed, 1),
        "models_used": meta.get("counts", {}),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Endometrial gold set LLM triage bench")
    ap.add_argument("--model", action="append",
                    default=None, help="Model(s) to test. Default: code + cloud chain.")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="Per-paper timeout in seconds (default 90)")
    ap.add_argument("--query",  default=QUERY)
    ap.add_argument("--claim",  default=CLAIM)
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args(argv)

    models = args.model or ["code", "gpt-oss:120b-cloud", "deepseek-v4-flash:cloud", "kimi-k2.6:cloud"]
    papers = gold_set()
    n_support  = sum(1 for p in papers if p["_expected_direction"] == "support")
    n_offtopic = sum(1 for p in papers if p["_expected_direction"] == "mention-only")

    print(f"Gold set: {len(papers)} ({n_support} support, {n_offtopic} off-topic)\n")
    print(f"{'Model':<28} {'Acc':>6} {'Strict':>8} {'OffTop':>8} {'Support':>9} {'Time':>8}")
    print("-" * 72)

    results = []
    for model in models:
        r = run_bench(model, timeout=args.timeout, query=args.query, claim=args.claim)
        results.append(r)
        mused = ",".join(f"{m}×{c}" for m, c in r["models_used"].items())
        print(
            f"  {r['model']:<26} {r['acc']:>6.3f} {r['strict']:>8.3f} "
            f"{r['offtopic_recall']:>8} {r['support_recall']:>9} {r['elapsed']:>7.1f}s"
            f"  [{mused}]"
        )

    if args.out_dir:
        import json
        from datetime import datetime
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        (out_dir / f"gold_bench_{ts}.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False)
        )
        print(f"\nSaved → {out_dir}/gold_bench_{ts}.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
