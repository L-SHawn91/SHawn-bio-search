# PAPER_MAPPING_INTEGRATION_STRATEGY_260401

- working folder: `/home/mdge/github/SHawn-bio-search`
- document class: `project`
- related repo reviewed: `/home/mdge/github/SHawn-paper-mapping`

## Actual review basis
Actual review result from `SHawn-paper-mapping`:
- repo mission is structured paper inventory, method extraction, claim mapping, citable-unit analysis, and sentence audit
- core 5-layer model is:
  1. `paper`
  2. `method`
  3. `claim`
  4. `citable_unit`
  5. `sentence_audit`
- active literature-analysis data belongs in `/media/mdge/4TB_MDGE/SH/papers`, not in the repo itself

## Strategic conclusion
`SHawn-bio-search` should not stop at retrieval bundles only.
It should emit retrieval outputs that are easy to promote into the 5-layer mapping system without pretending that promotion has already happened.

That means the retrieval engine should become better at **mapping-readiness**, not manuscript reasoning.

## Recommended architecture

### Layer 1. Retrieval detection layer (`SHawn-bio-search`)
Purpose:
- detect candidate papers and datasets
- normalize metadata
- identify local holdings
- mark verification risk states

Recommended minimum output fields:
- paper candidate id / citation_key
- title
- authors
- year
- journal
- DOI / PMID / PMCID
- source and source_hits
- abstract
- access state
- local hit state
- record_status
- collision_prone_author_year
- manuscript_ready=false

### Layer 2. Mapping-ingest bridge
Purpose:
- transform retrieval hits into rows that can be triaged in paper-mapping / SH/papers

Recommended bridge artifacts:
- `PAPER_CANDIDATE_MASTER.tsv`
- `DATASET_CANDIDATE_MASTER.tsv`
- `COLLISION_WARNING_TABLE.tsv`
- `PROMOTION_QUEUE.tsv`

These are not final paper-mapping layers yet.
They are the staging layer between search and structured analysis.

### Layer 3. Structured mapping layer (`SHawn-paper-mapping` / `SH/papers`)
Promotion targets:
- `paper`
- `method`
- `claim`
- `citable_unit`
- `sentence_audit`

Promotion rules:
- retrieval hit -> `paper` row after bibliographic lock
- method/model details -> `method`
- explicit result or interpretation -> `claim`
- citation-usable paraphrase or close-support text -> `citable_unit`
- manuscript sentence support check -> `sentence_audit`

## How paper and dataset detection should improve

### A. Paper detection datafication
Current problem:
- search results are rich enough to read, but not yet optimized as triage-ready tables

Improve by adding:
- `record_status`
- `verification_priority`
- `collision_group_id`
- `candidate_reason`
- `promotion_ready`
- `local_evidence_available`
- `mapping_target_suggestion`

Recommended `mapping_target_suggestion` values:
- `paper_only`
- `paper_plus_claim_review`
- `paper_plus_method`
- `paper_plus_citable_unit`
- `sentence_audit_candidate`

### B. Dataset detection datafication
Datasets should not remain only as repository hits.
Add fields that help mapping and later project use:
- `dataset_type`
- `organism`
- `tissue`
- `platform`
- `raw_available`
- `processed_available`
- `accession`
- `repository`
- `project_relevance_hint`
- `paper_link_candidate`

Recommended staged artifacts:
- `DATASET_CANDIDATE_MASTER.tsv`
- `DATASET_PAPER_LINK_CANDIDATES.tsv`

### C. Search-to-mapping promotion logic
Recommended rule:
1. retrieve candidate
2. verify metadata lock
3. assign promotion target
4. push to mapping queue
5. promote into `paper` / `method` / `claim` / `citable_unit` / `sentence_audit`

## High-value new artifacts for SHawn-bio-search

### 1. `PAPER_CANDIDATE_MASTER.tsv`
One row per detected paper candidate.
Suggested columns:
- citation_key
- first_author
- year
- title
- journal
- doi
- pmid
- source
- source_hits
- local_hit
- collision_prone_author_year
- record_status
- verification_priority
- promotion_ready
- mapping_target_suggestion
- notes

### 2. `DATASET_CANDIDATE_MASTER.tsv`
One row per detected dataset candidate.
Suggested columns:
- repository
- accession
- title
- organism
- tissue
- platform
- raw_available
- processed_available
- source_query
- project_relevance_hint
- paper_link_candidate
- promotion_ready

### 3. `COLLISION_WARNING_TABLE.tsv`
For citation-risk control.
Suggested columns:
- collision_group_id
- first_author
- year
- candidate_count
- titles
- journals
- dois
- resolution_status

### 4. `PROMOTION_QUEUE.tsv`
Bridge from retrieval to structured mapping.
Suggested columns:
- record_id
- record_type
- current_status
- next_target_layer
- lock_status
- urgency
- assigned_reason

## External/community directions worth checking
Based on current search results, potentially relevant external/community resources include:
- OpenClaw medical skills collections for biomedical workflow ideas
- community OpenClaw skill registries/lists for Zotero- and research-oriented skills
- Zotero management skills that support DOI lookup, duplicate detection, export, PDF checking, and metadata repair

These are not direct drop-in replacements, but they may help with:
- Zotero sync/repair workflows
- duplicate/collision detection ideas
- structured citation export patterns

## Recommended next implementation order
1. keep retrieval outputs provisional by default
2. add mapping-readiness fields to search outputs
3. export `PAPER_CANDIDATE_MASTER.tsv`
4. export `DATASET_CANDIDATE_MASTER.tsv`
5. add collision warning table
6. connect promotion queue to `SHawn-paper-mapping` / `SH/papers` workflow

## Bottom line
The optimization target is:
- not “make search outputs more manuscript-like”
- but “make search outputs more promotion-ready for structured paper mapping and dataset intelligence workflows”
