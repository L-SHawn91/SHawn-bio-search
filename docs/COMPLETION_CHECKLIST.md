# Completion Checklist (v1 backend-ready)

This checklist defines the current "v1 retrieval backend" completion line for `SHawn-bio-search`.

## Core retrieval
- [x] Multi-source paper retrieval works
- [x] Multi-source dataset retrieval works
- [x] Query-time deduplication is applied
- [x] Source provenance is preserved (`source_hits`, `source_ids`)

## Metadata and access enrichment
- [x] DOI/PMID/PMCID/accession normalization fields are preserved when available
- [x] Open-access enrichment is supported via Unpaywall
- [x] `status`, `downloadable`, and `pdf_reachable` are separated
- [x] Local paper-library lookup is supported

## Local library behavior
- [x] Zotero root can be supplied explicitly
- [x] Zotero root can be supplied via `ZOTERO_ROOT`
- [x] Zotero root fallback auto-discovery exists for local/dev environments

## Export contract
- [x] `SEARCH_RESULTS.json`
- [x] `DATASETS.json`
- [x] `AVAILABILITY_REPORT.md`
- [x] `LOCAL_LIBRARY_MATCHES.csv`
- [x] `SEARCH_LOG.md`
- [x] compatibility export remains possible where needed

## Merge behavior
- [x] Duplicate paper records are merged, not just dropped
- [x] Source lists are merged across duplicate hits
- [x] Author normalization handles common reversed two-token variants heuristically

## Documentation
- [x] README describes scope and outputs
- [x] README explains Zotero path resolution order
- [x] PROJECT defines the retrieval/backend boundary
- [x] Output schema is documented
- [x] Troubleshooting notes exist

## Not part of this completion line
These belong to `SHawn-academic-research` or later phases:
- manuscript-facing scoring
- evidence synthesis and final adjudication
- contradiction-aware writing
- section drafting / review drafting
- polished exploration UI
