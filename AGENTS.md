# SHawn-bio-search — Agent Instructions

**Skill name**: `bio-search`
**Repo identifier**: `SHawn-bio-search` (canonical case)
**PyPI / CLI / module**: `shawn-bio-search` (PyPI), `shawn-bio-search` / `sbs` (CLI), `shawn_bio_search` (Python module). Lowercase intentional per PyPI/PEP convention.
**Platform**: cross-platform (Mac + Linux, identical code)
**Repo role**: pure stateless library. No persistent state outside caller's request.
**Peer repos**: imported by `SHawn-paper-mapping`, `SHawn-bioinfo`, `SHawn-academic-research`, `SHawn-paper-assist`.

See canonical API contract: `SHawn-paper-mapping/rules/repo_boundaries.md`.

---

## Read order on session start

1. `README.md` — feature overview + 10-source map
2. `SKILL.md` — skill activation triggers and role boundaries
3. `CLAUDE.md` — Claude-Code-specific usage examples (optional)
4. `~/GitHub/SHawn-paper-mapping/rules/repo_boundaries.md` — federation contract

---

## When to activate

Trigger for:
- 논문 검색 / paper search / literature lookup / 선행연구
- citation verify / verify reference / 인용 검증
- 데이터셋 검색 / dataset discovery / GEO/SRA/PRJNA accession
- DOI / PMID / PMCID 정규화

Do NOT activate for:
- PDF claim/method extraction → `paper-mapping`
- Manuscript synthesis → `shawn-academic-research`
- Production formatting → `SHawn-paper-assist`
- Linux analysis execution → `shawn-bioinfo`

---

## Non-negotiable rules

1. **Library-pure**. No side effects beyond what the caller explicitly requests (HTTP fetch, file write to caller-specified path, etc.). No background daemons, no auto-syncs, no implicit cache writes outside the function call.
2. **No imports of other federation repos**. bio-search is the bottom of the dependency stack. All other repos import bio-search; bio-search imports nothing federation-specific.
3. **PyPI/CLI/module name = lowercase forever**. Never rename `shawn-bio-search` → `SHawn-bio-search` in `pyproject.toml`, `[project.scripts]`, or import paths. Repo identifier (filesystem, GitHub) is `SHawn-bio-search`; package metadata is `shawn-bio-search`.
4. **Cross-platform invariants**. Code must run identically on Mac and Linux. Never hardcode `~/Library/CloudStorage/...` (Mac) or `/media/mdge/...` (Linux).
5. **Stateless verify**. `verify_citation()` and `verify_dataset()` must never depend on local cache state for correctness. Cache is optional speedup only.

---

## Canonical usage patterns

### Paper search
```python
from shawn_bio_search import search_papers
results = search_papers(
    query="endometrial organoid bovine",
    claim="optional claim text",
    sources=["pubmed", "europe_pmc", "openalex", "biorxiv"],
)
```

### Citation verification
```python
from shawn_bio_search.sources.pubmed import verify_citation
result = verify_citation(
    first_author="Kwon",
    year="2024",
    context_keywords=["endometrial", "organoid"],
    context_sentence="<sentence where citation appears>",
    use_crossref=True,
    use_semanticscholar=True,
)
# Check result._verification_confidence: HIGH | MEDIUM | LOW | MISMATCH
```

### CLI
```bash
shawn-bio-search "<query>" --claim "<optional>" --max 10
sbs "<query>"  # short alias
```

---

## Output guarantees

- Returns dataclasses or dicts, not raw HTTP payloads
- DOI/PMID/PMCID always normalized (lowercase doi, no prefix on PMID)
- Source attribution preserved (`_source_provenance` field)
- Verification confidence always populated when verify-* functions called

---

## Where to escalate

| Situation | Escalate to |
|---|---|
| User wants to extract claims from a PDF | paper-mapping |
| User wants the search results saved to corpus.db | paper-mapping (bio-search returns; paper-mapping persists) |
| User wants Methods-section primer specs from search results | bio-skills (future) + academic-research |
| User wants OA download saved to Zotero folder | use bio-search.fetcher; persistence is caller's responsibility |
