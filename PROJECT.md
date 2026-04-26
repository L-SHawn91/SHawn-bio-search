# PROJECT

- project_slug: SHawn-bio-search
- display_name: SHawn-bio-search
- status: active-repo
- working_folder: <repo-root>
- repo_name: SHawn-bio-search
- main_session: proj-SHawn-bio-search
- source_of_truth: filesystem-first
- write_policy: limited-writeback

## Goal
Operate and evolve the SHawn bio search discovery engine under the shared github repo container.

## Scope
`SHawn-bio-search` is the global discovery and retrieval-enrichment layer.

Core responsibilities:
- find papers across global literature sources
- find datasets across public repositories
- normalize identifiers and metadata
- deduplicate records
- check access/downloadability
- match papers against the local Zotero-backed paper library when configured
- emit structured retrieval outputs for downstream use

Out of scope:
- project-aware interpretation
- evidence synthesis and final adjudication
- scoring as a manuscript-facing decision layer
- section drafting or review writing

Those responsibilities belong to downstream analysis or writing layers, not to this retrieval repository.

## Positioning
`SHawn-bio-search` should be treated as a reproducible biomedical retrieval backend rather than a chat-first literature assistant or graph-exploration UI.

It competes best on:
- structured paper/dataset discovery
- access/downloadability enrichment
- local paper-library awareness
- automation and downstream handoff

It does not compete primarily on:
- polished citation-map exploration UX
- conversational answer generation
- manuscript-facing synthesis
