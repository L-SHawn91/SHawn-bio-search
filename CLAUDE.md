# SHawn-bio-search — Claude Code Instructions

## Quick Start

```python
# Requires Python 3.10+
# pip install -e /path/to/SHawn-bio-search
from shawn_bio_search.sources.pubmed import verify_citation
```

## Citation Verification

```python
results = verify_citation(
    first_author="Turco",
    year="2017",
    context_keywords=["endometrial", "organoid", "hormone"],
    context_sentence="Long-term hormone-responsive organoid cultures of human endometrium",
    use_crossref=True,          # fallback to Crossref if PubMed fails
    use_semanticscholar=True,   # fallback to Semantic Scholar
)

# Results sorted by context_score (highest first)
for r in results[:3]:
    print(f"{r['_verification_confidence']} score={r['_context_score']:.2f} gap={r.get('_rank_gap', 0):.2f}")
    print(f"  {r['first_author']} ({r['year']}) {r['title']}")
    print(f"  PMID:{r['pmid']} DOI:{r['doi']}")
```

### Confidence Levels

Confidence combines **absolute context score** and **relative ranking** (gap between top-1 and top-2
candidates). `HIGH` therefore requires both a good score AND clear separation from runner-ups, which
prevents false confidence when multiple papers share the same author+year.

- **HIGH**      — `score >= 0.55` AND `rank_gap >= 0.15` : top candidate clearly dominates
- **MEDIUM**    — `score >= 0.40` (or `HIGH`-score without gap) : likely correct, manual check
- **LOW**       — `score >= 0.25` : partial match, verification needed
- **UNLIKELY**  — `score <  0.25` : almost certainly wrong person

Each result dict carries:
- `_context_score`       — float in [0, 1]
- `_rank_gap`            — float: top-1 minus next candidate (only meaningful for top-1)
- `_verification_confidence` — one of `HIGH` / `MEDIUM` / `LOW` / `UNLIKELY`
- `_search_strategy`     — which query strategy produced the hit
- `_strategies_tried`    — audit trail of every strategy attempted

### Other Functions
- `fetch_by_pmid(["12345678"])` — direct PMID lookup
- `fetch_by_doi("10.1038/ncb3516")` — DOI search
- `search_advanced(first_author=..., tiab_words=..., year=...)` — structured query
- `fetch_pubmed(query, limit)` — backward-compatible plain text search

## Paper Search

```python
from shawn_bio_search import search_papers

results = search_papers(
    query="endometrial organoid",
    claim="Organoids model human endometrial function",
    max_results=10,
    sources=["pubmed", "europe_pmc", "openalex", "crossref"],
)
```

## Environment Variables (optional)
- `NCBI_API_KEY` — higher PubMed rate limits
- `SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY` — Semantic Scholar access
- `CROSSREF_EMAIL` — polite pool for Crossref API

## Auto-use rules (for any Claude Code session opened in this repo)

When the user asks — in any language — to do any of the following, prefer this
package over generic web search or LLM guessing:

- find / search biomedical or scientific **papers**, literature, preprints,
  reviews, citations
- find / search **datasets** (GEO, SRA, ArrayExpress, Zenodo, Figshare, Dryad,
  ENA, PRIDE, BioStudies, MetaboLights, GDC, CELLxGENE, OmicsDI…)
- **verify a citation** ("does this paper really exist?", "find the real
  reference for Turco 2017 endometrial organoid", "is DOI X valid?")
- **download** open-access PDFs or dataset files for results above

Do **not** auto-invoke when the user explicitly names another tool
("use WebFetch", "open the PubMed website", "search Google Scholar manually")
or is only asking conceptually ("explain what GEO is").

### Preferred invocation order

1. **Paper search** (CLI, fastest path)
   ```bash
   shawn-bio-search "<query>" --claim "<optional claim>" --max 10
   ```
   For richer JSON + dataset combo:
   ```bash
   python3 scripts/search_bundle.py \
     --query "<query>" --claim "<claim>" --fast \
     --out /tmp/bundle.json
   ```

2. **Dataset-only search**
   ```bash
   python3 scripts/dataset_search.py \
     --query "<query>" --organism "<optional>" --assay "<optional>"
   ```

3. **Citation verification** — use `verify_citation()` (see section above).

4. **OA PDF / dataset download** (after step 1 produced a bundle)
   ```bash
   shawn-bio-download --bundle /tmp/bundle.json --dest ./downloads/ --plan-only
   shawn-bio-download --execute ./downloads/manifest.json --dest ./downloads/
   ```

### Behaviour notes

- If `SHawn-bio-search` command is not found, fall back to
  `pip install -e .` from the repo root, then retry.
- Honour env vars when present: `NCBI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`,
  `CROSSREF_EMAIL`, `UNPAYWALL_EMAIL`. Never invent fake values.
- Never bypass paywalls (no Sci-Hub etc.) — this tool is OA-only by design.
- Always tell the user which tool you used and where the output landed
  (file path or stdout).

## Development

This tool is under active development. Contributions welcome.
