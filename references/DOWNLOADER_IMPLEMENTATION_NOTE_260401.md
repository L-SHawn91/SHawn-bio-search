# DOWNLOADER_IMPLEMENTATION_NOTE_260401

- working folder: `/home/mdge/github/SHawn-bio-search`
- document class: `project`

## What was added
A conservative downloader prototype was added:
- `scripts/download_to_zotero_staging.py`

## Current behavior
- reads `PAPER_CANDIDATE_MASTER.tsv`
- reads `SEARCH_RESULTS.json`
- defaults to `download_routing_class = safe_auto`
- requires explicit `--zotero-root` or `ZOTERO_ROOT`
- writes only into Zotero staging subdirs
- skips likely duplicates based on DOI/title filename heuristics
- supports `--dry-run`

## Why dry-run first is important
The search layer can still return unstable or redirected PDF URLs.
So operational use should begin with:
- `--dry-run`
- review sample target paths
- inspect duplicate-skip behavior
- then enable real download only after confirming Zotero root and staging policy

## Recommended first-use pattern
```bash
python3 scripts/download_to_zotero_staging.py \
  --paper-candidate-master outputs/staging_validation_260401_v2/PAPER_CANDIDATE_MASTER.tsv \
  --search-results outputs/staging_validation_260401_v2/SEARCH_RESULTS.json \
  --zotero-root /path/to/Zotero/papers \
  --routing-class safe_auto \
  --dry-run
```

## Current limitations
- no PDF content-type verification beyond URL fetch success
- no checksum registry yet
- duplicate detection is filename heuristic only
- no RIS/BibTeX/Zotero DB integration yet
- review-first queue is not auto-approved for download

## Next improvement targets
1. verify content type and file size before keeping file
2. add download manifest TSV/JSON
3. record downloaded paths back into queue/status table
4. support optional DOI-title journal lock check before write
5. integrate with Zotero attachment conventions if needed
