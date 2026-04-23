# ZOTERO_DOWNLOAD_ROUTING_PLAN_260401

- working folder: `/home/mdge/github/SHawn-bio-search`
- document class: `project`

## Goal
If a paper is downloadable, route it into the Zotero paper root in a controlled, metadata-aware way.

## Principle
Downloading into the Zotero paper root must not happen at the raw retrieval-candidate stage.
It should happen only after minimum bibliographic lock and duplicate-risk checks.

## Why this matters
If raw retrieval candidates are downloaded directly into the Zotero paper store:
- author-year collisions can create duplicate or mislabeled PDFs
- concept-fit candidates can pollute the paper library
- DOI-missing records can create ambiguous filenames
- later local-first search quality becomes worse instead of better

## Recommended states before download
A candidate should satisfy at least these before automated Zotero-root download:
- `record_status` is no longer plain `candidate`
- `title_locked = true`
- `doi_locked = true` when DOI exists or is expected
- `collision_prone_author_year = false` OR collision has been manually resolved
- `access.downloadable = true`
- `access.pdf_url` is present and reachable

Recommended additional safety gates:
- `journal_locked = true`
- local duplicate check by DOI/title hash completed
- `manuscript_ready` does not need to be true, but metadata lock should be sufficient

## Download routing classes

### Class A. Safe auto-download
Conditions:
- DOI present and locked
- title locked
- collision not present or resolved
- local duplicate not found
- pdf_url reachable

Action:
- allowed to auto-download into Zotero root staging area

### Class B. Review-first download
Conditions:
- pdf_url exists
- metadata partially locked
- collision risk or duplicate ambiguity remains

Action:
- add to download queue only
- do not auto-download yet

### Class C. No-download
Conditions:
- no stable PDF URL
- DOI/title unresolved
- collision unresolved
- metadata too incomplete

Action:
- keep as retrieval candidate only

## Recommended Zotero-root flow
1. retrieve candidate
2. metadata lock check
3. collision/duplicate check
4. classify into A/B/C
5. if A: download to Zotero staging folder under Zotero root
6. verify file integrity and duplicate status
7. promote local_library metadata

## Storage design recommendation
Do not initially write straight into mixed final Zotero folders.
Use a controlled subtree under the Zotero root, such as:
- `<ZOTERO_ROOT>/_incoming_shawn_bio_search/`
- `<ZOTERO_ROOT>/_incoming_shawn_bio_search/review_needed/`
- `<ZOTERO_ROOT>/_incoming_shawn_bio_search/locked_downloads/`

This keeps retrieval-side ingestion auditable and reversible.

## Suggested new output fields
For paper candidates:
- `download_routing_class`: `safe_auto` | `review_first` | `blocked`
- `download_candidate`: boolean
- `download_reason`: string
- `target_zotero_subdir`: string
- `local_duplicate_risk`: `low` | `medium` | `high`

For promotion/download queue:
- `download_status`: `not_applicable` | `queued` | `ready` | `blocked` | `downloaded`
- `download_target`
- `download_source_url`

## Filename policy recommendation
Prefer deterministic filenames based on locked metadata, e.g.:
- `DOI__FirstAuthor_Year__ShortTitle.pdf`

If DOI missing, do not auto-download unless explicitly reviewed.

## Integration consequence
`SHawn-bio-search` should not become a blind paper downloader.
It should become a downloader-aware retrieval layer that:
- detects whether download is possible
- decides whether download is safe
- routes safe items toward Zotero-root staging
- leaves ambiguous items in a review queue

## Immediate implementation target
Near-term outputs should at least support:
- download candidate flagging
- target Zotero subdir suggestion
- queue export for review-first handling
