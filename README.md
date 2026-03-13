# Shawn-Bio-Search

> Multi-source biomedical literature search with claim-level evidence scoring

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A unified Python interface for searching biomedical literature across 9+ sources with intelligent claim-level evidence evaluation.

## Features

- **10 Integrated Sources**: PubMed, Semantic Scholar, Scopus, Google Scholar, Europe PMC, OpenAlex, Crossref, ClinicalTrials.gov, bioRxiv, medRxiv
- **Claim-Level Scoring**: Verify scientific claims with evidence scores
- **Multiple Output Formats**: Plain text, Markdown, JSON
- **CLI + Python API**: Use from command line or import as module
- **Deduplication**: Automatic removal of duplicate papers across sources

## Source support matrix (maturity)

| Source | Cost | Key needed | Maturity | Notes |
|---|---|---|---|---|
| PubMed | Free | Optional (`NCBI_API_KEY`) | Stable | Biomedical primary source |
| OpenAlex | Free | No | Stable | Broad metadata/citation graph |
| Crossref | Free | No | Stable | DOI metadata normalization |
| Europe PMC | Free | No | Stable | OA coverage strong |
| Semantic Scholar | Free (rate-limited) | Yes (`SEMANTIC_SCHOLAR_API_KEY` or `S2_API_KEY`) | Beta | Good recall/impact signals |
| Scopus | Paid/institutional | Yes | Conditional | Institution contract required |
| Google Scholar (SerpAPI) | Paid key | Yes (`SERPAPI_API_KEY`) | Conditional | Recall expansion only |
| ClinicalTrials/bioRxiv/medRxiv | Free | No | Experimental | best-effort adapters |

## Installation

```bash
pip install shawn-bio-search
```

Or install from source:

```bash
git clone https://github.com/L-SHawn91/shawn-bio-search.git
cd shawn-bio-search
pip install -e .
```

## Quick Start

### Command Line

```bash
# Basic search
shawn-bio-search -q "organoid stem cell"

# Verify a claim
shawn-bio-search -q "endometrial organoid" \
  -c "ECM is essential for organoid formation"

# JSON output
shawn-bio-search -q "cancer immunotherapy" -f json -o results.json

# Specific sources only
shawn-bio-search -q "COVID-19" -s pubmed,europe_pmc
```

### Python API

```python
from shawn_bio_search import search_papers

# Basic search
results = search_papers(query="organoid stem cell", max_results=10)
print(results.to_plain())

# Claim verification
results = search_papers(
    query="endometrial organoid",
    claim="ECM is essential for organoid formation"
)
for paper in results.papers[:5]:
    print(f"{paper['title']}: score={paper.get('evidence_score', 0)}")

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

### With Evidence Scoring

When using `-c/--claim`:

```
[pubmed] Evidence: 0.85 | Clevers H (2016). Organoids: Modeling Development...
[europe_pmc] Evidence: 0.78 | Gjorevski N et al. (2016). Designer matrices...
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
shawn-bio-search -q "adenomyosis IVF" -c "Adenomyosis worsens IVF outcomes" -f json
```

### C) Full writing workflow mode

Use the pipeline script to generate review/citation/evidence packages.

## Paper Writing Mode (v2)

One-command pipeline for manuscript-ready evidence package:

```bash
./scripts/run_paper_writing_mode_v2.sh \
  "adenomyosis ivf meta-analysis" \
  "Adenomyosis is associated with poorer IVF outcomes." \
  "Pregnancy endpoints should be secondary in early-phase uterine fibrosis trials." \
  "./outputs/adeno_v2" \
  --zotero-root "/path/to/Zotero/papers" \
  --fast --with-kaggle --with-cellcog --with-unpaywall --with-orcid
```

Outputs include:
- bundle JSON
- review list markdown
- claim evidence report (support/contradict/uncertain + gaps)
- citations (md/csv/bib)
- missing-in-zotero checklist
- datasets+ (optional Kaggle/Cellcog snapshot)
- bundle_enriched.json (optional ORCID/Unpaywall enrichment: oa_status, oa_pdf_url, orcid_matches)

## First-time installation workflow

```bash
git clone https://github.com/L-SHawn91/shawn-bio-search.git
cd shawn-bio-search
pip install -e .
cp .env.example .env
# edit .env: set at least ZOTERO_ROOT, optional API keys
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
  --zotero-root "$ZOTERO_ROOT" \
  --fast --with-kaggle
```

## Evidence scoring (what the score means)

`evidence_score` is a ranking aid, not proof by itself. It combines:
- claim/hypothesis term overlap
- source quality/metadata completeness (DOI etc.)
- support vs contradiction signal from abstract-level text

Recommended interpretation:
- `supporting` and `contradicting` papers should both be reviewed
- high score without DOI/full text should be treated as provisional
- final citation decisions should use sentence-level verification
- source weight now contributes to ranking (PubMed/OpenAlex/Semantic Scholar strong; Google Scholar/preprints more conservative)
- Semantic Scholar requests are rate-limited to ~1 request/second inside the adapter

## Documentation

- [Supported Sources](docs/SOURCES.md)
- [API Reference](docs/API.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## About the Author

**Dr. Soohyung (SHawn) Lee** — Biomedical Researcher & Developer

Dr. SHawn is a researcher specializing in organoid technology, endometrial biology, and computational bio-research workflows. As the founder of **SHawn Lab**, he develops intelligent research tools that bridge the gap between vast scientific literature and actionable insights.

**Research Focus:**
- Endometrial organoid models
- Reproductive biology and regenerative medicine
- Evidence-based literature mining
- AI-assisted research workflows

**SHawn Lab Ecosystem:**
- 🔬 **SHawn-BIO**: Biomedical research intelligence platform
- 🌐 **SHawn-WEB**: Digital lab and knowledge management
- 🤖 **SHawn-BOT**: Automated research assistant
- 📚 **shawn-bio-search**: Multi-source literature search (this project)

> "Literature should be diagnosed, not just searched."
> — Dr. SHawn

## License

MIT License - see [LICENSE](LICENSE) file.

## Citation

If you use Shawn-Bio-Search in your research, please cite:

```
Lee S. (2026). Shawn-Bio-Search: Multi-source biomedical literature search 
with claim-level evidence scoring. GitHub repository.
https://github.com/L-SHawn91/shawn-bio-search
```

## Contact

- Issues: [GitHub Issues](https://github.com/L-SHawn91/shawn-bio-search/issues)
- Email: leseichi@gmail.com
