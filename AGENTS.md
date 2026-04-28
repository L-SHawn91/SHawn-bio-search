# SHawn-bio-search — Agent Instructions

**Skill name**: `shawn-bio-search`
**Platform**: Mac + Linux (pure library, no local state).
**Repo role**: stateless biomedical literature search and dataset fetcher library. Provides PubMed, Europe PMC, OpenAlex, Crossref, Semantic Scholar, bioRxiv/medRxiv, ClinicalTrials.gov search plus OA PDF and dataset download.
**Peer repos**: `SHawn-bioinfo` (Linux analysis hub), `SHawn-paper-mapping` (Mac claim/corpus hub), `SHawn-academic-research` (Mac manuscript hub), `SHawn-BIO` (integration layer).

Canonical portable skill contract: `SKILL.md`.
See also: `CLAUDE.md` in this repo for full API examples.

---

## When to activate

Trigger this skill for:
- "논문 찾아줘", "paper search", "literature search", "find papers on..."
- "데이터셋 찾아", "dataset search", "GEO search", "SRA search"
- "인용 검증", "verify citation", "is this paper real?"
- "PDF 다운로드", "download open-access paper"
- Any request to search biomedical databases programmatically

Do NOT activate this skill for:
- Paper corpus indexing or claim extraction (-> `paper-mapping`)
- scRNA-seq / bulk RNA-seq analysis execution (-> `bioinfo`)
- Manuscript drafting or writing (-> `academic-research`)
- Vault organization or note templates (-> `Lab-Vault`)
- General web search unrelated to biomedical literature

---

## Read order

1. `SKILL.md` — portable OpenClaw/Claude/Codex/Ollama activation contract
2. This file (`AGENTS.md`) — vendor-neutral agent rules and repo role
3. `CLAUDE.md` — full API contract, CLI usage, code examples
4. `pyproject.toml` — entry points and dependencies
5. `shawn_bio_search/` — source code (search.py, cli.py, scoring.py, sources/)

---

## Non-negotiable rules

1. **Stateless library** — this repo owns no databases, registries, or persistent state. It returns results; callers persist them.
2. **Never bypass paywalls** — OA-only by design for automated downloads. No Sci-Hub, no mirror sites, no proxy tricks, no credential capture.
3. **Honour API keys** — use `NCBI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `CROSSREF_EMAIL`, `UNPAYWALL_EMAIL` when present. Never invent fake values.
4. **No heavy deps** — this package stays lightweight. Heavy analysis deps belong in `SHawn-bioinfo`.
5. **Download root is fixed** — all paper/PDF downloads on LINUXclaw must be saved directly in `/home/mdge/Clouds/onedrive/Papers/Zotero/논문` unless the user explicitly requests another folder. Do not create `_incoming`, staging, topic/date subfolders, repo `outputs/`, `Downloads/`, `/tmp`, or other ad-hoc PDF destinations. Keep manifests/logs/reports in repo `outputs/` when audit files are needed; only actual PDFs go to the Zotero `논문` root.
6. **No symlink deployment** — expose this repo to OpenClaw, Claude, Codex, and Ollama through direct repo paths or copied adapters. Do not create skill symlinks.

### Institutional access boundary — current authorized network

- The user's current institutional, campus, hospital, or library subscription network is **authorized institutional access**, not a paywall-bypass mechanism.
- Automated SHawn-bio-search downloaders must **not** impersonate, scrape credentials, tunnel, or evade publisher access controls.
- If a paper is unavailable through OA routes but may be accessible through the user's current legitimate network/library browser session, use `institutional_access_ready` where that route is available; otherwise use `institutional_access_candidate`.
- Use `shawn-bio-institutional` (or `python scripts/open_institutional_queue.py` for legacy callers) to batch-open DOI/publisher pages and write an audit TSV across Codex, Claude, OpenClaw, Ollama, and plain shell environments.
- Browser-assisted/manual institutional downloads must preserve an audit trail: DOI/title, publisher landing page, current access route, download timestamp, local root path, sha256, and verification result.
- Actual PDFs still go directly to `/home/mdge/Clouds/onedrive/Papers/Zotero/논문`; reports/manifests stay in repo `outputs/`.

---

## Federation integration

| Direction | Protocol |
|---|---|
| `paper-mapping` -> here | Calls `shawn_bio_search.sources.*` for DOI/title lookup during corpus enrichment |
| `bioinfo` -> here | Calls `shawn_bio_search.download.fetcher` for GEO/SRA dataset download |
| `SHawn-BIO` -> here | Wraps CLI as integration layer for paper-writing mode |
| `academic-research` -> here | Citation verification during manuscript drafting |

---

## Preferred invocation

```bash
# Paper search (CLI)
shawn-bio-search "<query>" --claim "<claim>" --max 10

# Dataset search
python3 scripts/dataset_search.py --query "<query>" --organism "<species>"

# Citation verification (Python)
from shawn_bio_search.sources.pubmed import verify_citation
results = verify_citation(first_author="Turco", year="2017",
                          context_keywords=["endometrial", "organoid"])
```

---

## Change log

- 2026-04-24 — initial AGENTS.md (vendor-neutral agent entry point)
- 2026-04-28 — added root SKILL.md as portable cross-environment skill contract
