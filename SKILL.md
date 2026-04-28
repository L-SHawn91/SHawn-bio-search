---
name: shawn-bio-search
description: Portable SHawn ecosystem skill for biomedical paper search, dataset discovery, citation verification, OA access checks, and retrieval bundles. Use for OpenClaw, Claude, Codex, Ollama-style prompt contexts, and any agent environment that needs programmatic biomedical evidence retrieval.
---

# SHawn Bio Search

This is the canonical portable skill entry point for `SHawn-bio-search`.

Use this skill when the user asks to:
- find biomedical or scientific papers, reviews, preprints, citations, or evidence
- search public biomedical datasets such as GEO, SRA, ENA, ArrayExpress, Zenodo, Figshare, Dryad, PRIDE, BioStudies, MetaboLights, GDC, CELLxGENE, or OmicsDI
- verify whether a citation, DOI, PMID, title, author/year pair, or reference is real
- build a machine-readable retrieval bundle for downstream paper mapping or manuscript work
- check open-access PDF availability or plan OA-only downloads

Do not use this skill as the primary tool for:
- claim extraction, corpus indexing, or citation graph mapping: use `SHawn-paper-mapping`
- RNA-seq/scRNA-seq/proteomics execution: use `SHawn-bioinfo`
- manuscript drafting or project-aware synthesis: use `SHawn-academic-research`
- vault organization or note templates: use the relevant SHawn knowledge/vault layer

## Environment Contract

This repo must work across OpenClaw, Claude, Codex, Ollama, and plain shell workflows.

- OpenClaw: load this repo directly as a skill root. Do not use a symlink.
- Claude: read this file first, then `CLAUDE.md` for Claude-specific details.
- Codex/agent runtimes: read this file first, then `AGENTS.md` for vendor-neutral agent rules.
- Ollama/local LLM: prepend this file, or a condensed derivative of it, as the system/context prompt before running retrieval commands.
- Shell/API users: use the Python package and CLI from this repo.

No symlink deployment is allowed for this skill. Use direct repo paths or copied adapters that point agents to this canonical repo.

Canonical repo path pattern:
- Linux: `~/github/SHawn-bio-search`
- macOS: `~/github/SHawn-bio-search`
- Override when needed: `SHAWN_BIO_SEARCH_HOME`

## Read Order

1. `SKILL.md` - portable activation contract and boundaries
2. `AGENTS.md` - vendor-neutral agent instructions
3. `CLAUDE.md` - Claude Code examples and defaults
4. `README.md` - user-facing package overview
5. `docs/AGENT_COMPATIBILITY.md` - cross-environment deployment notes
6. `pyproject.toml` - entry points
7. `shawn_bio_search/` and `scripts/` - implementation

## Preferred Invocation

Install locally if the command is not available:

```bash
python3 -m pip install -e ~/github/SHawn-bio-search
```

Paper search:

```bash
shawn-bio-search -q "endometrial organoid" --max 10 -f json -o /tmp/shawn-bio-search-results.json
```

Paper search with claim context:

```bash
shawn-bio-search -q "H9 ESC definitive endoderm endometrial epithelial progenitor" \
  --claim "H9 ESCs can be differentiated toward endometrial epithelial progenitors" \
  --max 10 \
  -f json \
  -o /tmp/shawn-bio-search-claim.json
```

Dataset search:

```bash
python3 ~/github/SHawn-bio-search/scripts/dataset_search.py \
  --query "endometrial organoid single cell RNA-seq" \
  --organism "Homo sapiens"
```

Retrieval bundle:

```bash
python3 ~/github/SHawn-bio-search/scripts/search_bundle.py \
  --query "endometrial organoid hormone response" \
  --claim "Endometrial organoids model hormone-responsive epithelium" \
  --fast \
  --out /tmp/shawn-bio-search-bundle.json
```

Institutional access queue:

```bash
shawn-bio-institutional --check-env
shawn-bio-institutional --queue ~/github/SHawn-bio-search/outputs/dhcr24_260427/DHCR24_INSTITUTIONAL_ACCESS_READY_260427.tsv \
  --limit 10 \
  --batch-size 5
shawn-bio-institutional --auth-provider-label "Yonsei University Library" --limit 10
```

Current network detection is enabled by default; pass `--no-detect-network` only when a fixed offline audit route is required. When the physical network and authenticated provider differ, set `--auth-provider-label` for the actual subscription provider.

Citation verification:

```python
from shawn_bio_search import verify_citation

hits = verify_citation(
    first_author="Turco",
    year="2017",
    context_keywords=["endometrial", "organoid", "hormone"],
)
```

## Download And Access Rules

Automated downloads are OA-only.

Never use Sci-Hub, mirror sites, credential scraping, proxy tricks, or publisher access evasion.

On LINUXclaw, actual paper PDFs must go directly to:

```text
/home/mdge/Clouds/onedrive/Papers/Zotero/논문
```

Do not create `_incoming`, staging, topic/date subfolders, repo `outputs/`, `Downloads/`, `/tmp`, or arbitrary PDF destinations unless the user explicitly asks.

Repo `outputs/` may hold search bundles, manifests, logs, and reports. Actual PDFs belong in the Zotero paper root above.

The user's current institutional/campus/hospital/library network access is authorized institutional access, not a bypass. If OA routes fail but institutional access may apply, mark the item as `institutional_access_ready` where the route is available; otherwise use `institutional_access_candidate`. Use `shawn-bio-institutional` to batch-open DOI/publisher pages in the normal browser and write an audit TSV. Preserve DOI/title, publisher page, current access route, timestamp, root PDF path, sha256, and verification result.

## Output Discipline

For every retrieval task, report:
- query and sources used
- output file path or stdout summary
- DOI/PMID/PMCID/accession identifiers when available
- confidence or limitations
- skipped keyed sources when keys are absent

Do not invent API keys or identifiers. Use configured env vars only:
- `NCBI_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY`
- `CROSSREF_EMAIL`
- `UNPAYWALL_EMAIL`
- source-specific institutional keys such as `SCOPUS_API_KEY`
