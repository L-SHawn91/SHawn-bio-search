---
name: bio-search
description: Biomedical paper and dataset discovery skill for the SHawn ecosystem. Use when the user needs literature search across PubMed, Semantic Scholar, Europe PMC, OpenAlex, Crossref, bioRxiv, medRxiv, ClinicalTrials.gov; citation verification by author+year+context; dataset discovery (GEO/SRA/PRJNA accessions); DOI/PMID/PMCID normalization; or local Zotero library lookup. Pure stateless library — no persistent state. Delegate manuscript synthesis to shawn-academic-research, claim extraction to paper-mapping, and analysis to shawn-bioinfo.
---

# SHawn-bio-search

Stateless biomedical discovery and verification library for the SHawn 6-repo federation.

## Trigger phrases

- 논문 검색 / paper search / literature lookup
- citation verify / verify reference / 인용 검증
- 데이터셋 검색 / dataset discovery / GEO accession
- 선행연구 / related work / prior literature
- DOI / PMID / PMCID 정규화

## Scope

Pure library — no filesystem state outside caller's request:

1. **Paper discovery** — `search_papers(query, claim, sources=[...])` across 10 sources with claim-level evidence scoring
2. **Citation verification** — `verify_citation(first_author, year, context_keywords)` returns HIGH/MEDIUM/LOW/MISMATCH confidence via Crossref + Semantic Scholar + PubMed
3. **Dataset discovery** — `dataset_search()`, accession enumeration (GSE/PRJNA/SRP/SRX/SRR/CNGB)
4. **Access enrichment** — DOI/PMID/PMCID normalization, OA status, downloadability checks
5. **Local library lookup** — Zotero-backed paper presence check

## Role boundary

- **NOT manuscript writing** — delegate to `shawn-academic-research`
- **NOT claim/method extraction** — delegate to `paper-mapping`
- **NOT analysis execution** — delegate to `shawn-bioinfo`
- **NOT production formatting** — delegate to `SHawn-paper-assist`

## Federation contract

Imported by all other federation repos. Cross-platform (Mac + Linux). PyPI-style package name (lowercase): `shawn-bio-search`. CLI: `shawn-bio-search`, `sbs`. Repo identifier: `SHawn-bio-search`.

See `~/GitHub/SHawn-paper-mapping/rules/repo_boundaries.md` for full federation contract.
