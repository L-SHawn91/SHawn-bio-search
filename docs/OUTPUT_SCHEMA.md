# SHawn-bio-search Output Schema

This document defines the preferred machine-facing output contract when `SHawn-bio-search` is used as the retrieval engine in the SHawn dual-engine architecture.

## Purpose

`SHawn-bio-search` should emit retrieval artifacts that are:
- stable enough for downstream automation
- rich enough for evidence interpretation
- narrow enough to avoid duplicating the reasoning layer

## Primary retrieval artifacts

Preferred files:
- `SEARCH_RESULTS.json`
- `DATASETS.json`
- `CITATIONS.md`
- `CITATIONS.bib`
- `SEARCH_LOG.md`
- `AVAILABILITY_REPORT.md`
- `LOCAL_LIBRARY_MATCHES.csv`

Current implementation note:
- existing scripts may still emit older handoff artifacts during transition
- the preferred direction is to standardize around retrieval, access, and local-library outputs rather than manuscript-facing evidence bundles

## 1) SEARCH_RESULTS.json

Purpose:
- normalized retrieval results and metadata

Top-level fields:
- `project` — optional project name or slug
- `backend` — should be `SHawn-bio-search`
- `mode` — optional retrieval mode such as `fast` or `full`
- `run_label` — stable run identifier
- `query` — original query
- `effective_query` — expanded/preset-adjusted query when applicable
- `generated_at` — ISO timestamp
- `results` — list of normalized search hits

Each item in `results` should prefer these fields:
- `citation_key`
- `source`
- `source_hits`
- `source_ids`
- `title`
- `authors`
- `year`
- `doi`
- `pmid`
- `pmcid`
- `url`
- `abstract`
- `access`
- `local_path`
- `zotero_match`

Recommended `access` subfields:
- `status` — `open` | `paywalled` | `restricted` | `unknown`
- `downloadable` — whether an OA location or download-like target was identified
- `pdf_reachable` — whether a lightweight HTTP reachability check suggests the PDF URL is actually reachable
- `check_method` — `unpaywall` | `pdf_url` | `oa_metadata` | `pubmed_metadata` | `landing_page_only` | source-specific
- `pdf_url`
- `license`

## 2) DATASETS.json

Purpose:
- normalized dataset candidates and repository metadata

Top-level fields:
- `project` — optional project name or slug
- `backend` — should be `SHawn-bio-search`
- `run_label` — stable run identifier
- `query` — original query
- `generated_at` — ISO timestamp
- `results` — list of normalized dataset hits

Each item in `results` should prefer these fields:
- `repository`
- `accession`
- `title`
- `organism`
- `data_type`
- `summary`
- `url`
- `download_url`
- `access`

## 3) CITATIONS.md

Purpose:
- readable citation ledger with minimal downstream cleaning

Each entry should include:
- citation key
- author
- year
- title
- DOI
- short relevance note

## 4) AVAILABILITY_REPORT.md

Purpose:
- human-readable summary of access status and local availability

Recommended sections:
- total paper candidates
- open / paywalled / unknown counts
- local library hit counts
- manual-fetch-needed list
- dataset repository counts

## 5) LOCAL_LIBRARY_MATCHES.csv

Purpose:
- operational table for locally available papers

Recommended columns:
- `title`
- `doi`
- `pmid`
- `access_status`
- `downloadable`
- `in_local_library`
- `match_type`
- `local_pdf_path`
- `pdf_url`

## 6) SEARCH_LOG.md

Purpose:
- trace of search behavior and retrieval conditions

Recommended sections:
- original query
- effective query
- project mode if used
- sources used
- source exclusions
- query expansion status
- retrieval warnings
- key limits and assumptions

## Boundary rule

This schema is for retrieval-facing outputs.
It should not drift into manuscript-facing synthesis.

That means these files may contain:
- access/downloadability metadata
- local-library match metadata
- candidate retrieval ranking
- source-aware ranking

But they should not contain:
- final contradiction reconciliation
- final manuscript verdict language
- polished review prose
- section-ready scientific narrative
- manuscript-facing project scores

Those belong to `SHawn-academic-research`.
