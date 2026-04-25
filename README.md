# Shawn-Bio-Search

> Global biomedical paper and dataset discovery with metadata normalization, access checks, and local library lookup

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A unified Python interface for discovering biomedical papers and datasets across global sources, normalizing metadata, checking access/downloadability, and identifying locally available papers.

## Scope

`SHawn-bio-search` is a **discovery and retrieval-enrichment layer** for reproducible biomedical search workflows.

It focuses on:
- global paper search
- dataset discovery across public repositories
- metadata normalization (DOI / PMID / PMCID / accession when available)
- deduplication across sources
- access/downloadability checks
- local Zotero-backed paper library lookup
- exportable machine-readable search bundles

It does **not** aim to be the manuscript-facing interpretation engine. Project-aware interpretation, evidence synthesis, scoring, and writing workflows should live in downstream analysis or writing layers rather than inside this repository.

## Features

- **17 Integrated Sources**: PubMed, Europe PMC, OpenAlex, Crossref, Semantic Scholar, ClinicalTrials.gov, bioRxiv, medRxiv, arXiv, OpenAIRE, F1000Research, DOAJ (free) plus Scopus, SciVal, Google Scholar (SerpAPI), CORE, Unpaywall (key/email-gated)
- **Paper + Dataset Discovery**: Find candidate literature and datasets from global sources
- **Access Enrichment**: Track DOI/PMID/PMCID, URLs, and downloadability status
- **Local Library Lookup**: Check whether a paper already exists in a Zotero-backed local paper store
- **Multiple Output Formats**: Plain text, Markdown, JSON
- **CLI + Python API**: Use from command line or import as module
- **Deduplication**: Automatic removal of duplicate papers across sources

## Source support matrix (maturity)

Default-on rules:
- **Free** sources are queried by default.
- **Keyed** sources are queried automatically only when their environment variable is set (otherwise skipped silently with a warning).

| Source | Cost | Key needed | Default-on | Maturity | Notes |
|---|---|---|---|---|---|
| PubMed | Free | Optional (`NCBI_API_KEY`) | Yes | Stable | Biomedical primary source |
| Europe PMC | Free | No | Yes | Stable | OA coverage strong |
| OpenAlex | Free | No | Yes | Stable | Broad metadata/citation graph |
| Crossref | Free | No | Yes | Stable | DOI metadata normalization |
| Semantic Scholar | Free (rate-limited) | Optional (`SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY`) | Yes | Beta | Good recall/impact signals; ~1 rps without key |
| ClinicalTrials.gov | Free | No | Yes | Experimental | best-effort adapter |
| bioRxiv | Free | No | Yes | Experimental | best-effort adapter |
| medRxiv | Free | No | Yes | Experimental | best-effort adapter |
| arXiv | Free | No | Yes | Beta | Quant bio / methods preprints |
| OpenAIRE | Free | No | Yes | Beta | EU OA aggregator |
| F1000Research | Free | No | Yes | Beta | Open peer review platform |
| DOAJ | Free | No | Yes | Beta | Directory of OA journals |
| Scopus | Paid / institutional | Yes (`SCOPUS_API_KEY`) | When key set | Conditional | Institution contract required |
| SciVal | Paid / institutional | Yes (`SCIVAL_API_KEY` or `SCOPUS_API_KEY`) | When key set | Conditional | Author metric enrichment only (FWCI, ScholarlyOutput) |
| Google Scholar (SerpAPI) | Paid key | Yes (`SERPAPI_API_KEY`) | When key set | Conditional | Recall expansion only |
| CORE | Free dev tier | Yes (`CORE_API_KEY`) | When key set | Beta | OA full-text aggregator |
| Unpaywall | Free | Email (`UNPAYWALL_EMAIL` or `CROSSREF_EMAIL`) | When email set | Stable | OA status / PDF resolution |

## Installation

```bash
pip install shawn-bio-search
```

Or install from source:

```bash
git clone https://github.com/L-SHawn91/SHawn-bio-search.git
cd SHawn-bio-search
pip install -e .
```

## Quick Start

### Command Line

```bash
# Basic search
shawn-bio-search -q "organoid stem cell"

# JSON output
shawn-bio-search -q "cancer immunotherapy" -f json -o results.json

# Focused source selection
shawn-bio-search -q "endometrial organoid" -s pubmed,europe_pmc,openalex

# Specific sources only
shawn-bio-search -q "COVID-19" -s pubmed,europe_pmc
```

### Python API

```python
from shawn_bio_search import search_papers

# Basic search
results = search_papers(query="organoid stem cell", max_results=10)
print(results.to_plain())

# Access raw data
import json
print(results.to_json())
```

## API Keys (Optional)

Some sources work better with API keys:

| Source | Environment Variable | Free Tier |
|--------|---------------------|-----------|
| Semantic Scholar | `SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY` | Free but 1 rps |
| Scopus | `SCOPUS_API_KEY` | Requires institutional access |
| Google Scholar | `SERPAPI_API_KEY` | Free tier available |
| PubMed | `NCBI_API_KEY` | Recommended for higher limits |

Set up your keys:

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_key_here"
export SCOPUS_API_KEY="your_key_here"
export SERPAPI_API_KEY="your_key_here"
export NCBI_API_KEY="your_key_here"
```

Or create a `.env` file (see `.env.example`).

## Output Format

### Plain Text (Default)

```
[pubmed] Clevers H (2016). Organoids: Modeling Development and Disease with Organoids. Cell. DOI: 10.1016/j.cell.2016.05.082

[europe_pmc] Gjorevski N et al. (2016). Designer matrices for intestinal stem cell and organoid culture. Nature. DOI: 10.1038/nature20168
```

## Quickstart by usage level

### A) Free mode (no paid keys)

```bash
shawn-bio-search -q "endometrial organoid" -f json -o results_free.json
```

### B) API-extended mode

```bash
export NCBI_API_KEY="..."
export SEMANTIC_SCHOLAR_API_KEY="..."   # recommended, 1 rps
export SERPAPI_API_KEY="..."            # optional
export SCOPUS_API_KEY="..."             # optional institutional
shawn-bio-search -q "adenomyosis IVF" -f json
```

### C) Retrieval bundle mode

Generate structured outputs for downstream tools:

```bash
python3 scripts/search_bundle.py \
  --query "adenomyosis" \
  --project-mode adenomyosis \
  --expand-query \
  --fast \
  --export-dual-engine-dir ./outputs/dual_engine_run
```

Preferred retrieval artifacts:
- `SEARCH_RESULTS.json`
- `DATASETS.json`
- `AVAILABILITY_REPORT.md`
- `LOCAL_LIBRARY_MATCHES.csv`
- `SEARCH_LOG.md`
- `CITATIONS.bib`

Example artifact fragments:

```json
{
  "citation_key": "10.1038_ncb3516",
  "source": "pubmed",
  "source_hits": ["pubmed", "openalex"],
  "doi": "10.1038/ncb3516",
  "access": {
    "status": "open",
    "downloadable": true,
    "pdf_reachable": true,
    "check_method": "unpaywall"
  },
  "local_library": {
    "found": true,
    "match_type": "doi"
  }
}
```

```json
{
  "repository": "geo",
  "accession": "GSE123456",
  "title": "Example dataset",
  "access": {
    "status": "open",
    "downloadable": true,
    "check_method": "repository"
  }
}
```

### D) Access + local library workflow

Use the pipeline scripts to enrich search results with open-access status, downloadable links, and local Zotero-backed paper availability where configured.

Zotero/local paper root resolution order:
1. `--zotero-root <path>`
2. `ZOTERO_ROOT` environment variable
3. auto-discovery of common local paths (for local/dev setups)

## First-time installation workflow

```bash
git clone https://github.com/L-SHawn91/SHawn-bio-search.git
cd SHawn-bio-search
pip install -e .
cp .env.example .env
# edit .env: API keys optional; ZOTERO_ROOT optional if you prefer explicit path config
set -a && source .env && set +a

# optional: Kaggle CLI credential bootstrap
mkdir -p ~/.kaggle
printf '{"username":"%s","key":"%s"}\n' "$KAGGLE_USERNAME" "$KAGGLE_KEY" > ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json

# smoke test (paper mode)
./scripts/run_paper_writing_mode_v2.sh \
  "adenomyosis ivf meta-analysis" \
  "Adenomyosis is associated with poorer IVF outcomes." \
  "Pregnancy endpoints should be secondary in early-phase uterine fibrosis trials." \
  "./outputs/smoke" \
  --fast --with-kaggle
```

If you want explicit control over the local paper store, add:

```bash
--zotero-root /path/to/Zotero/papers
```

## Ranking and boundary notes

`SHawn-bio-search` may still use lightweight ranking heuristics internally to improve retrieval order and source coverage.

Those heuristics are intended only for:
- retrieval prioritization
- first-pass candidate surfacing
- metadata completeness preference

They are **not** the final scientific interpretation layer.
Project-aware scoring, evidence adjudication, contradiction handling, and writing-oriented judgment belong in downstream analysis and writing workflows, not in the retrieval core.

Operational notes:
- source weight may contribute to retrieval ranking (PubMed/OpenAlex/Semantic Scholar generally stronger; Google Scholar/preprints more conservative)
- high-ranked results without DOI/full text should still be treated as provisional
- Semantic Scholar requests are rate-limited to ~1 request/second inside the adapter

## Positioning

`SHawn-bio-search` is not trying to be a general-purpose chat answer engine or a citation-graph exploration UI.

It is positioned as a **reproducible biomedical retrieval backend** focused on:
- multi-source paper and dataset discovery
- access/downloadability enrichment
- local library awareness
- machine-readable export for downstream research workflows

### Practical framing

Use **SHawn-bio-search** when you want a controllable, automatable, auditable biomedical retrieval workflow focused on search, normalization, access checks, and downstream-ready artifacts.

## Documentation

- [Supported Sources](docs/SOURCES.md)
- [API Reference](docs/API.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Completion checklist](docs/COMPLETION_CHECKLIST.md)
- [Dual-engine boundary](docs/DUAL_ENGINE_BOUNDARY.md)
- [Output schema](docs/OUTPUT_SCHEMA.md)

## License

MIT License - see [LICENSE](LICENSE) file.

## Citation

If you use Shawn-Bio-Search in your research, please cite the repository URL and the release or commit you used.

## Contact

- Issues: [GitHub Issues](https://github.com/L-SHawn91/SHawn-bio-search/issues)
