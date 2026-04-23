# REFERENCE_VERIFICATION_IMPROVEMENT_PLAN_260401

- working folder: `/home/mdge/github/SHawn-bio-search`
- document class: `project`
- source report reviewed: `/media/mdge/4TB_MDGE/SH/papers/06_reports/REFERENCE_VERIFICATION_ROUTINE_260401.md`

## Actual review basis
Actual review result:
- Failure case and routine were reviewed from the SH/papers report.
- Current repo docs already state that `SHawn-bio-search` is a retrieval backend, not a manuscript-facing adjudication layer.
- However, current outputs and wording still leave room to confuse retrieval candidates with locked references.
- Current canonical local repo exists at `/home/mdge/github/SHawn-bio-search`.
- The thread-starter path `/home/mdge/github/SHawn-bio-search-public` does not currently exist on disk.

## Why repo improvement is needed
The HGF / Sugawara case shows that retrieval-stage similarity is not sufficient for manuscript recommendation.
A collision-prone author-year cluster can produce a wrong final recommendation if:
- title is not matched exactly
- journal is not matched explicitly
- DOI is not matched explicitly
- retrieval candidates are shown too close to final citation language

## Core improvement target
Strengthen the repo so that it is structurally hard to confuse:
1. retrieval candidate
2. metadata-checked candidate
3. locked reference

## Proposed repo changes

### 1. Output schema: add explicit verification-state fields
Add or standardize these fields for paper-level retrieval outputs:
- `record_status`: `candidate` | `metadata_checked` | `locked_reference`
- `collision_prone_author_year`: boolean
- `locked_fields`: object containing
  - `authors_locked`
  - `year_locked`
  - `title_locked`
  - `journal_locked`
  - `doi_locked`
- `manuscript_ready`: boolean
- `manuscript_ready_reason`: short string

Rule:
- default retrieval output should be `record_status = candidate`
- `manuscript_ready` must default to `false`
- only a downstream verified workflow should ever promote a paper to manuscript-ready

### 2. Legacy evidence export: rename or warn more aggressively
Current file name `EVIDENCE_CANDIDATES.json` is directionally correct, but the internal field `directness` is too easy to overread as a final claim-evidence verdict.

Recommended change:
- keep compatibility if needed
- but rename the field or add an explicit warning layer:
  - `retrieval_directness_hint` instead of `directness`
  - `final_adjudication: not_performed`
  - `manuscript_use: prohibited_until_verified`

### 3. Collision warning support
Add explicit collision detection for papers sharing:
- first author
- year
- overlapping title keyword cluster

When triggered:
- set `collision_prone_author_year = true`
- emit warning in `SEARCH_LOG.md`
- optionally emit `COLLISION_WARNINGS.json`
- block any manuscript-ready export path unless title/journal/DOI are locked

### 4. Bibliographic lock rule in docs
Document a hard rule:
A reference must not be recommended in manuscript-facing text unless all five are locked together:
- authors
- year
- title
- journal
- DOI

### 5. Boundary docs: strengthen wording
Current boundary docs are good, but they should explicitly mention:
- retrieval candidates must never be treated as final citations
- author-year only is insufficient during recommendation/evaluation
- concept-fit does not replace exact bibliographic verification

### 6. Local-first workflow alignment
Because this repo is part of a validated-local-first workflow, outputs should distinguish:
- local hit found
- local hit metadata checked
- local hit locked for manuscript use

Suggested fields:
- `local_library.found`
- `local_library.match_type`
- `local_library.metadata_checked`
- `local_library.locked_reference_match`

## High-priority files to update
1. `README.md`
   - add warning that retrieval bundles are provisional
   - add brief reference-verification rule

2. `docs/OUTPUT_SCHEMA.md`
   - add verification-state and collision fields
   - make manuscript-ready default false

3. `docs/DUAL_ENGINE_BOUNDARY.md`
   - explicitly forbid treating retrieval output as final citation recommendation

4. `KNOWN_GAPS.md`
   - add collision handling and bibliographic lock as active gaps

5. `ROADMAP.md`
   - add author-year collision warning + bibliographic lock signaling as near-term priorities

6. `scripts/export_dual_engine_bundle.py`
   - add default provisional-state fields
   - downgrade `directness` to a retrieval-side hint
   - append warnings when legacy evidence export is used

## Recommended implementation order
1. docs and schema warnings
2. output-field additions
3. collision detection support
4. legacy evidence export clarification
5. optional dedicated collision warning artifact

## Practical design rule
`SHawn-bio-search` should help prevent citation mistakes without becoming the final manuscript reasoning engine.
That means:
- stronger retrieval-side warnings
- stronger metadata-state signaling
- no false implication that a retrieval candidate is publication-ready
