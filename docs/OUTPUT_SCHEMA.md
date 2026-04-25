# SHawn-bio-search Output Schema

This document defines the preferred machine-facing output contract when `SHawn-bio-search` is used as the retrieval engine in the SHawn dual-engine architecture (and optionally in the 3-way linkage with `SHawn-paper-mapping` + `SHawn-academic-research`).

## Purpose

`SHawn-bio-search` should emit retrieval artifacts that are:
- stable enough for downstream automation
- rich enough for evidence interpretation
- narrow enough to avoid duplicating the reasoning layer

## Primary retrieval artifacts

Preferred files:
- `SEARCH_RESULTS.json`
- `EVIDENCE_CANDIDATES.json` (claim-aware retrieval output)
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
- `evidence_score` — optional float 0.0–1.0 retrieval-side relevance heuristic
- `evidence_label` — optional retrieval-side hint (`support` | `contradict` | `uncertain` | `retrieval-hint`)

Recommended `access` subfields:
- `status` — `open` | `paywalled` | `restricted` | `unknown`
- `downloadable` — whether an OA location or download-like target was identified
- `pdf_reachable` — whether a lightweight HTTP reachability check suggests the PDF URL is actually reachable
- `check_method` — `unpaywall` | `pdf_url` | `oa_metadata` | `pubmed_metadata` | `landing_page_only` | source-specific
- `pdf_url`
- `license`

## 2) EVIDENCE_CANDIDATES.json

Purpose:
- claim-aware retrieval candidates grouped by claim for downstream synthesis
- consumed by `SHawn-academic-research` when claim-level interpretation is needed

Top-level fields:
- `project` — optional project name or slug
- `backend` — should be `SHawn-bio-search`
- `run_label` — stable run identifier
- `generated_at` — ISO timestamp
- `claims` — list of claim-keyed candidate groups

Each item in `claims` should prefer these fields:
- `claim_id`
- `claim_text`
- `candidates` — list of evidence candidate records

Each candidate should prefer these fields:
- `bucket` — `support` | `contradict` | `uncertain` | `mention-only` (downstream folds `mention-only` into `uncertain`)
- `citation_key`
- `reason`
- `directness` — `direct` | `indirect` | `transferred`
- `model_context`
- `notes`
- `evidence_score` — optional retrieval-side score for the candidate
- `evidence_label` — optional retrieval-side hint

`EVIDENCE_CANDIDATES.json` is strictly a **retrieval-side proposal**; wrapper-side interpretation (final `bucket` assignment, `directness` resolution, confidence framing) is owned by `SHawn-academic-research`.

## 3) DATASETS.json

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

## 4) CITATIONS.md

Purpose:
- readable citation ledger with minimal downstream cleaning

Each entry should include:
- citation key
- author
- year
- title
- DOI
- short relevance note

## 5) AVAILABILITY_REPORT.md

Purpose:
- human-readable summary of access status and local availability

Recommended sections:
- total paper candidates
- open / paywalled / unknown counts
- local library hit counts
- manual-fetch-needed list
- dataset repository counts

## 6) LOCAL_LIBRARY_MATCHES.csv

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

## 7) SEARCH_LOG.md

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

## 8) `verify_citation()` results

Purpose:
- output of `shawn_bio_search.sources.pubmed.verify_citation()` for confirming whether a cited paper actually exists and matches the surrounding context

Each item in the returned list (sorted by `_context_score` descending) carries the standard normalized paper fields (`title`, `authors`, `year`, `doi`, `pmid`, `pmcid`, `url`, `abstract`, `first_author`, ...) plus:

- `_context_score` — float 0.0–1.0, token-overlap match against `context_keywords` and `context_sentence`
- `_verification_confidence` — bucketed label derived from `_context_score`:

| Label | `_context_score` range | Interpretation |
|---|---|---|
| `HIGH` | `>= 0.60` | Correct paper with high certainty |
| `MEDIUM` | `>= 0.35` | Likely correct, manual check recommended |
| `LOW` | `>= 0.15` | Uncertain match — context is weak |
| `MISMATCH` | `< 0.15` | Wrong paper (different field/species/topic) |

`_verification_confidence` is a retrieval-side hint only. Downstream consumers (`SHawn-academic-research`) decide whether to accept, request re-verification, or surface a conflict to the writer.

## Cross-tool evaluation linkage

The retrieval bundle emitted by `SHawn-bio-search` is the producer in a dual-engine (and optionally 3-way) linkage:

```
SHawn-bio-search  →  SHawn-paper-mapping  →  SHawn-academic-research
   (retrieval)        (normalization)         (synthesis + evaluation)
```

Downstream consumers of this schema:

- **`SHawn-paper-mapping`** ingests candidate paper lists to populate `PAPER_MASTER` rows (see that repo's `docs/integration/BIO_SEARCH_EXPORT_CONTRACT_260401.md`). Uses `citation_key`, `authors`, `year`, `title`, `doi`, `pmid`, `abstract` from `SEARCH_RESULTS.json`.
- **`SHawn-academic-research`** ingests `SEARCH_RESULTS.json` and, when present, `EVIDENCE_CANDIDATES.json` (see that repo's `docs/INPUT_SCHEMA_FROM_BIO_SEARCH.md`). The `evidence_score`, `evidence_label`, `access.status`, and `local_library.found` fields contribute to the downstream `REPORT.md` evaluation axes (detailed in `docs/EVALUATION_HANDOFF.md`).

Keep this schema stable enough that either downstream consumer can be added or removed without invalidating the bundle.

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

Those belong to downstream analysis and writing layers.
