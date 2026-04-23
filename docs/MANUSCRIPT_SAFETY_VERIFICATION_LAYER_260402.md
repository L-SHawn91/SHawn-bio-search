# Manuscript Safety Verification Layer (260402)

## Why this exists

`SHawn-bio-search` is a retrieval engine, not a manuscript-safe citation engine.

Recent failure cases showed that retrieval candidates can be mistakenly promoted too early, especially when:
- author-year collisions exist
- the journal/year/prefix pattern looks plausible
- a DOI is attached before bibliographic lock is complete

That means the operational boundary must be explicit and machine-readable.

## Required promotion ladder

Every paper record must move through these stages in order:

1. `retrieved`
   - search hit only
   - not recommendation-safe
   - may contain incomplete or noisy metadata

2. `metadata_locked`
   - author
   - year
   - title
   - journal
   confirmed together to a practical working level
   - still not necessarily DOI-safe

3. `doi_locked`
   - DOI confirmed against the same bibliographic record
   - PMID/PMCID added when available
   - collision risk reviewed

4. `manuscript_safe`
   - bibliographic lock completed
   - role tagged for writing use
   - fit judged at sentence/claim level
   - safe for manuscript-facing recommendation

Rule: no record may jump directly from `retrieved` to `manuscript_safe`.

## Required core fields

Each retrieval-side paper record should expose at least:
- `verification_status`
- `record_status`
- `metadata_locked`
- `doi_candidate`
- `doi_locked`
- `pmid`
- `pmcid`
- `collision_risk`
- `collision_group_id`
- `requires_title_journal_doi_lock`
- `manuscript_ready`
- `manuscript_ready_reason`

## DOI handling rule

DOI should not be treated as a final field at early retrieval stage.

Preferred semantics:
- `doi_candidate`: raw retrieved DOI-like value
- `doi_locked`: boolean after bibliographic confirmation
- `doi`: exposed as final/locked DOI only when `doi_locked=true`

Operational implication:
- if DOI has not been locked, downstream text should say `DOI: verification required` rather than printing it as final

## Collision warning rule

If records share:
- same first author
- same year
- overlapping journal/title/topic cluster

then mark:
- `collision_risk: high`
- `requires_title_journal_doi_lock: true`
- `manuscript_ready: false`

This should remain true until the collision is explicitly resolved.

## Output framing rule

Default output framing should be candidate-oriented, not recommendation-oriented.

Preferred retrieval bundle fields:
- claim or clause
- candidate paper
- metadata confidence
- DOI confidence
- role hint (`direct`, `partial`, `contextual`, `background`)
- overreach risk
- manuscript-ready (`yes/no`)

## Failure examples to remember

### Chen DOI mismatch case
A Fertility and Sterility DOI was attached to the wrong 2016 paper because title/journal/DOI were not locked together.

### HGF / Sugawara collision-type risk
Similar author-year-topic clusters can produce plausible but wrong manuscript-facing recommendations if title/journal/DOI locking is skipped.

## Implementation priority

Immediate priorities for `SHawn-bio-search`:
1. make verification state impossible to ignore in output
2. separate `doi_candidate` from locked DOI semantics
3. emit collision warnings early
4. keep manuscript-safe promotion as an explicit downstream step
5. prevent retrieval artifacts from rendering like final recommendations by default
