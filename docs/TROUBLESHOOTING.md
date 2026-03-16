# Troubleshooting

## Common checks

### 1) No Zotero/local paper matches found
Check resolution order for the local paper store:
1. `--zotero-root <path>`
2. `ZOTERO_ROOT`
3. auto-discovery of common local paths

If needed, pass the path explicitly:

```bash
python3 scripts/search_bundle.py \
  --query "endometrial organoid" \
  --fast \
  --export-dual-engine-dir ./outputs/test \
  --zotero-root /path/to/Zotero/papers
```

### 2) Open access appears true but `pdf_reachable=false`
This is expected in some cases.

`SHawn-bio-search` now distinguishes:
- `status=open` — OA metadata suggests access is available
- `downloadable=true` — a download-like target or OA location was found
- `pdf_reachable=true` — a lightweight HTTP check suggests the PDF URL is actually reachable

Some publishers block `HEAD` requests or use indirect delivery flows, so `pdf_reachable=false` does not always mean the paper is unavailable.

### 3) Missing Semantic Scholar / Scopus / Google Scholar results
Check API keys:
- `SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY`
- `SCOPUS_API_KEY`
- `SERPAPI_API_KEY`

### 4) Duplicate authors still appear after source merge
Author normalization is heuristic-based. Most `family/given-initial` and reversed two-token variants are consolidated, but some ambiguous source-specific name formats may still need refinement.

### 5) Expected retrieval artifacts are missing
For the retrieval bundle flow, confirm `--export-dual-engine-dir` was provided.

Expected core outputs:
- `SEARCH_RESULTS.json`
- `DATASETS.json`
- `AVAILABILITY_REPORT.md`
- `LOCAL_LIBRARY_MATCHES.csv`
- `SEARCH_LOG.md`

Optional compatibility/output extras may also appear depending on the workflow.
