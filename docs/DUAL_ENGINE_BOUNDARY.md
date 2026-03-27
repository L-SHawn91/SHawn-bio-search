# Retrieval vs Analysis Boundary

## Core rule
- `SHawn-bio-search` = retrieval engine
- downstream analysis/writing layers = reasoning and synthesis engine

These layers are designed to work together, but they should not collapse into one another.

## What SHawn-bio-search owns

`SHawn-bio-search` is responsible for:
- multi-source literature retrieval
- dataset retrieval
- identifier normalization (DOI / PMID / PMCID / accession when available)
- metadata enrichment
- deduplication
- access/downloadability checks
- local Zotero-backed library lookup when configured
- source-aware retrieval ranking
- query expansion
- exportable search bundles

Typical outputs:
- `SEARCH_RESULTS.json`
- `DATASETS.json`
- `CITATIONS.md`
- `CITATIONS.bib`
- `SEARCH_LOG.md`
- `AVAILABILITY_REPORT.md`
- `LOCAL_LIBRARY_MATCHES.csv`

## What SHawn-bio-search should not own

To avoid duplication, `SHawn-bio-search` should not become the manuscript-facing interpretation engine.

Avoid pushing these responsibilities into this repo:
- long-form literature review writing
- section drafting for manuscript prose
- contradiction reconciliation as a final verdict layer
- project-specific narrative synthesis
- manuscript-facing scoring or verdict language
- final claim adjudication intended for publication text
- polished discussion/conclusion writing

## What downstream analysis/writing layers own

Downstream analysis/writing layers are responsible for:
- project framing
- canonical working folder resolution
- research mode choice (`fast` vs `full`)
- search strategy oversight
- claim-to-evidence synthesis
- support / contradict / uncertain interpretation
- contradiction-aware reasoning
- gap analysis
- section drafting
- manuscript-facing report generation

Typical outputs:
- `REPORT.md`
- `CLAIM_EVIDENCE.md`
- `SECTION_DRAFT.md`
- `GAP_ANALYSIS.md`
- project-facing interpreted citation bundles

## Integration contract

Recommended handoff from `SHawn-bio-search` to downstream analysis/writing layers:

### Retrieval-side outputs
- `SEARCH_RESULTS.json`
- `DATASETS.json`
- `CITATIONS.md`
- `CITATIONS.bib`
- `SEARCH_LOG.md`
- `AVAILABILITY_REPORT.md`
- `LOCAL_LIBRARY_MATCHES.csv`

### Analysis-side consumption
Downstream analysis/writing layers should read those artifacts and then perform:
- evidence consolidation
- contradiction mapping
- confidence judgment
- section-ready synthesis
- manuscript-aware wording

## Practical rule of thumb

If the question is:
- "find" / "retrieve" / "search" / "expand sources" / "check access" / "find downloadable PDFs" / "see if it's already in Zotero" / "normalize identifiers" → use `SHawn-bio-search`
- "interpret" / "synthesize" / "compare evidence" / "score importance" / "draft" / "write review text" / "explain contradiction" → use downstream analysis/writing layers

## Design philosophy

This is a loose-coupled dual-engine architecture.

That means:
- no duplicated source adapters in downstream analysis/writing layers
- no duplicated narrative synthesis engine in `SHawn-bio-search`
- file-contract handoff preferred over hidden internal coupling
- retrieval and judgment remain separable for auditability

## Current implementation note

`SHawn-bio-search` may still contain lightweight ranking or labeling helpers when they improve retrieval quality.
That is acceptable as long as they remain retrieval aids and do not drift into full manuscript-facing reasoning or final project-level judgment.
