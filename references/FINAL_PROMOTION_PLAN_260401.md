# FINAL_PROMOTION_PLAN_260401

- working folder: `/home/mdge/github/SHawn-bio-search`
- document class: `project`

## Goal
Promote successfully downloaded safe-auto PDFs from Zotero staging into the final `papers/` layer in a controlled way.

## Current observed structure
Actual check result:
- Zotero paper root exists at `/home/mdge/Clouds/onedrive/Papers/Zotero/papers`
- current staging subtree exists:
  - `_incoming_shawn_bio_search/`
  - `_incoming_shawn_bio_search/locked_downloads/`
- at least one final topic folder already exists under root:
  - `Organoids/`

## Core rule
Promotion should not mean “dump into papers root blindly”.
It should mean:
- move from incoming staging
- into a deliberate final shelf/folder
- after minimal verification and destination classification

## Promotion states
### State 1. staged_downloaded
- file downloaded successfully into `_incoming_shawn_bio_search/locked_downloads`
- manifest entry exists
- PDF header check passed

### State 2. promotion_ready
Conditions:
- DOI present or other stable identifier acceptable
- no unresolved collision risk
- duplicate check against final target passed
- destination folder determined

### State 3. promoted_final
- file moved from staging to final shelf under `papers/`
- promotion logged in manifest/promotion log

## Recommended destination policy
Promotion target should not default to root flat storage.
Use one of these policies:

### Policy A. topic shelf
If mapping/topic is known:
- e.g. `papers/Organoids/`
- e.g. `papers/Endometrium/`
- e.g. `papers/Organoids/Endometrial/`

### Policy B. fallback shelf
If topic is not confidently known:
- `papers/_promoted_shawn_bio_search/`

This is still final-layer storage, but avoids cluttering root directly.

## Minimum promotion checklist
Before promotion:
- file exists in staging
- `%PDF-` header verified
- manifest has `downloaded`
- DOI/title duplicate check against final shelf passed
- collision status resolved or absent
- destination folder assigned

## Recommended outputs/logs
- `PROMOTION_LOG.tsv`
- optional `FINAL_LIBRARY_MATCHES.tsv`

Suggested promotion log columns:
- timestamp
- citation_key
- source_stage_path
- final_path
- destination_policy
- status
- note

## Immediate implementation suggestion
Create a conservative promotion script that:
1. reads `DOWNLOAD_MANIFEST.tsv`
2. selects `status=downloaded`
3. verifies file still exists and begins with `%PDF-`
4. chooses destination folder
5. skips duplicates
6. moves file from incoming to final folder
7. writes `PROMOTION_LOG.tsv`

## Design choice for now
Because topic inference is not yet strong enough, use:
- known explicit destination when provided by user/operator
- otherwise fallback to `papers/_promoted_shawn_bio_search/`

This still satisfies the user's intent of storing under `papers/`, while preserving control and auditability.
