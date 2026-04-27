# SHawn-bio-search — Claude Code Instructions

## Canonical status

`SHawn-bio-search` is the canonical SHawn ecosystem retrieval repo.
If you detect a parallel lowercase repo line (`shawn-bio-search`), treat it as a feature-source or forensic line, not the default home. New integration work should land here first unless the user explicitly says otherwise.

The repo-root `SKILL.md` is the portable OpenClaw/Claude/Codex/Ollama skill contract. Read `SKILL.md` first, then this file for Claude-specific examples and defaults. Do not expose this repo through skill symlinks; use direct repo paths or copied adapters.

## Quick Start

```python
# Requires Python 3.10+
# pip install -e /path/to/shawn-bio-search
from shawn_bio_search.sources.pubmed import verify_citation
```

## Citation Verification

```python
results = verify_citation(
    first_author="Turco",
    year="2017",
    context_keywords=["endometrial", "organoid", "hormone"],
    context_sentence="Long-term hormone-responsive organoid cultures of human endometrium",
    use_crossref=True,          # fallback to Crossref if PubMed fails
    use_semanticscholar=True,   # fallback to Semantic Scholar
)

# Results sorted by context_score (highest first)
for r in results[:3]:
    print(f"{r['_verification_confidence']} score={r['_context_score']:.2f}")
    print(f"  {r['first_author']} ({r['year']}) {r['title']}")
    print(f"  PMID:{r['pmid']} DOI:{r['doi']}")
```

### Confidence Levels
- **HIGH** (>=0.6): Correct paper with high certainty
- **MEDIUM** (>=0.35): Likely correct, manual check recommended
- **LOW** (>=0.15): Uncertain match
- **MISMATCH** (<0.15): Wrong paper (different field/species)

### Other Functions
- `fetch_by_pmid(["12345678"])` — direct PMID lookup
- `fetch_by_doi("10.1038/ncb3516")` — DOI search
- `search_advanced(first_author=..., tiab_words=..., year=...)` — structured query
- `fetch_pubmed(query, limit)` — backward-compatible plain text search

## Paper Search

```python
from shawn_bio_search import search_papers

results = search_papers(
    query="endometrial organoid",
    claim="Organoids model human endometrial function",
    max_results=10,
    sources=["pubmed", "europe_pmc", "openalex", "crossref"],
)
```

## Environment Variables (optional)
- `NCBI_API_KEY` — higher PubMed rate limits
- `SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY` — Semantic Scholar access
- `CROSSREF_EMAIL` — polite pool for Crossref API

## Auto-use rules (for any Claude Code session opened in this repo)

When the user asks — in any language — to do any of the following, prefer this
package over generic web search or LLM guessing:

- find / search biomedical or scientific **papers**, literature, preprints,
  reviews, citations
- find / search **datasets** (GEO, SRA, ArrayExpress, Zenodo, Figshare, Dryad,
  ENA, PRIDE, BioStudies, MetaboLights, GDC, CELLxGENE, OmicsDI…)
- **verify a citation** ("does this paper really exist?", "find the real
  reference for Turco 2017 endometrial organoid", "is DOI X valid?")
- **download** open-access PDFs or dataset files for results above

Do **not** auto-invoke when the user explicitly names another tool
("use WebFetch", "open the PubMed website", "search Google Scholar manually")
or is only asking conceptually ("explain what GEO is").

### Preferred invocation order

1. **Paper search** (CLI, fastest path)
   ```bash
   shawn-bio-search "<query>" --claim "<optional claim>" --max 10
   ```
   For richer JSON + dataset combo:
   ```bash
   python3 scripts/search_bundle.py \
     --query "<query>" --claim "<claim>" --fast \
     --out /tmp/bundle.json
   ```

2. **Dataset-only search**
   ```bash
   python3 scripts/dataset_search.py \
     --query "<query>" --organism "<optional>" --assay "<optional>"
   ```

3. **Citation verification** — use `verify_citation()` (see section above).

4. **OA PDF / dataset download** (after step 1 produced a bundle)

   **Required PDF destination on LINUXclaw:**
   `/home/mdge/Clouds/onedrive/Papers/Zotero/논문`

   Save actual paper PDFs directly in this root. Do **not** create `_incoming`, staging, topic/date subfolders, repo `outputs/`, `Downloads/`, `/tmp`, or arbitrary PDF destinations unless the user explicitly requests a different folder.

   Repo `outputs/` may hold search bundles, manifests, logs, and reports. Actual downloaded PDFs belong directly under the Zotero `논문` root.

   ```bash
   DEST="/home/mdge/Clouds/onedrive/Papers/Zotero/논문"
   shawn-bio-download --bundle /tmp/bundle.json --dest "$DEST" --plan-only \
     --manifest /tmp/manifest.json
   shawn-bio-download --execute /tmp/manifest.json --dest "$DEST"
   ```

### Behaviour notes

- If `shawn-bio-search` command is not found, fall back to
  `pip install -e .` from the repo root, then retry.
- Honour env vars when present: `NCBI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`,
  `CROSSREF_EMAIL`, `UNPAYWALL_EMAIL`. Never invent fake values.
- Never bypass paywalls (no Sci-Hub, mirrors, proxy tricks, credential capture, or publisher access evasion). Automated downloads are OA-only by design.
- Konkuk University 교내 네트워크 / library subscription access is allowed only as **authorized institutional access**, not as a bypass. If OA routes fail, mark the record as `institutional_access_candidate` and move it to a browser-assisted/manual step using the user's legitimate library/network session. Preserve DOI/title, publisher page, access route (`konkuk_institutional_access`), timestamp, root PDF path, sha256, and verification result.
- Always tell the user which tool you used and where the output landed
  (file path or stdout).

## Development

This tool is under active development. Contributions welcome.
