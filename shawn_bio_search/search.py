"""Core search functionality for Shawn-Bio-Search."""

import json
import os
from typing import Any, Dict, List, Optional, Union

from .sources import FREE_SOURCES, KEYED_SOURCES
from .sources.pubmed import fetch_pubmed
from .sources.europe_pmc import fetch_europe_pmc
from .sources.openalex import fetch_openalex
from .sources.crossref import fetch_crossref
from .sources.clinicaltrials import fetch_clinicaltrials
from .sources.biorxiv import fetch_biorxiv
from .sources.medrxiv import fetch_medrxiv
from .sources.semanticscholar import fetch_semanticscholar
from .sources.arxiv import fetch_arxiv
from .sources.openaire import fetch_openaire
from .sources.core import fetch_core
from .sources.unpaywall import fetch_unpaywall
from .sources.f1000research import fetch_f1000research
from .sources.doaj import fetch_doaj

# Optional sources (require API keys)
from .sources.scopus import fetch_scopus, search_scopus_authors, fetch_scopus_author_publications
from .sources.scival import fetch_scival_author_metrics
from .sources.google_scholar import fetch_google_scholar

from .scoring import score_paper
from .formatter import format_results
from .presets import apply_project_preset
from .query_expansion import expand_query


class SearchResult:
    """Container for search results."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.count = data.get("count", 0)
        self.papers = data.get("papers", [])
        self.warnings = data.get("warnings", [])

    def to_json(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)

    def to_plain(self, top_n: int = 10) -> str:
        return format_results(self.papers, fmt="plain", top_n=top_n)

    def to_markdown(self, top_n: int = 10) -> str:
        return format_results(self.papers, fmt="markdown", top_n=top_n)


class AuthorSearchResult:
    """Container for author-centric search/profile results."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.count = len(data.get("authors", []))
        self.authors = data.get("authors", [])
        self.warnings = data.get("warnings", [])

    def to_json(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)

    def to_plain(self, top_n: int = 10) -> str:
        lines = []
        for idx, a in enumerate(self.authors[:top_n], start=1):
            fwci = a.get("scival", {}).get("FieldWeightedCitationImpact")
            scholarly_output = a.get("scival", {}).get("ScholarlyOutput")
            lines.append(
                f"{idx}. {a.get('display_name') or a.get('name')} | author_id={a.get('author_id')} | "
                f"affiliation={a.get('affiliation') or '-'} | scopus_docs={a.get('document_count', 0)} | "
                f"sample_pubs={a.get('publication_count', 0)} | FWCI={fwci if fwci is not None else 'n/a'} | "
                f"ScholarlyOutput={scholarly_output if scholarly_output is not None else 'n/a'}"
            )
        if self.warnings:
            lines.append("Warnings: " + " | ".join(self.warnings))
        return "\n".join(lines)

    def to_markdown(self, top_n: int = 10) -> str:
        lines = ["| # | Author | Author ID | Affiliation | Scopus Docs | Sample Pubs | FWCI | Scholarly Output |", "|---|---|---|---|---:|---:|---:|---:|"]
        for idx, a in enumerate(self.authors[:top_n], start=1):
            fwci = a.get("scival", {}).get("FieldWeightedCitationImpact")
            scholarly_output = a.get("scival", {}).get("ScholarlyOutput")
            lines.append(
                f"| {idx} | {a.get('display_name') or a.get('name')} | {a.get('author_id')} | {a.get('affiliation') or '-'} | "
                f"{a.get('document_count', 0)} | {a.get('publication_count', 0)} | {fwci if fwci is not None else ''} | {scholarly_output if scholarly_output is not None else ''} |"
            )
        if self.warnings:
            lines.append("")
            lines.append("**Warnings:** " + " | ".join(self.warnings))
        return "\n".join(lines)


def _resolve_sources(
    sources: Optional[Union[List[str], str]],
    all_names: List[str],
) -> List[str]:
    """Normalize the `sources` argument to a concrete list of source names.

    - None or "free": free sources + keyed sources whose env var is configured
    - "all": every known source
    - list: passthrough
    """
    if isinstance(sources, str):
        key = sources.strip().lower()
        if key == "all":
            return all_names
        if key == "free":
            sources = None
        else:
            raise ValueError(f"Unknown sources preset: {sources!r}. Use 'free', 'all', or a list.")

    if sources is None:
        configured_keyed = [
            name for name, env_vars in KEYED_SOURCES.items()
            if any(os.getenv(v) for v in env_vars)
        ]
        return list(FREE_SOURCES) + configured_keyed

    return list(sources)


def search_papers(
    query: str,
    claim: str = "",
    hypothesis: str = "",
    max_results: int = 10,
    sources: Optional[Union[List[str], str]] = None,
    expand: bool = False,
    project_mode: str = "",
) -> SearchResult:
    """Search papers across multiple sources.

    Args:
        query: Search query string
        claim: Optional claim to verify (enables claim-level scoring)
        hypothesis: Optional hypothesis to test
        max_results: Maximum results per source
        sources: Either a list of source names, or a string preset:
            - "free" / None: every source that works without an API key plus any
              keyed source whose environment variable is configured
            - "all": every source (keyed ones skip cleanly when unconfigured)
            - Explicit list: use exactly those sources
        expand: Expand the query with lightweight biomedical synonyms
        project_mode: Apply a project-aware preset (e.g. endometrial-organoid-review)

    Returns:
        SearchResult object containing papers and metadata

    Example:
        >>> results = search_papers(
        ...     query="organoid stem cell niche",
        ...     claim="ECM is essential for organoid formation",
        ...     sources="free",
        ... )
        >>> print(results.to_plain())
    """
    preset_info = apply_project_preset(query=query, claim=claim, project_mode=project_mode)
    effective_query = preset_info["effective_query"]
    effective_claim = preset_info["effective_claim"]
    if expand:
        effective_query = expand_query(effective_query)

    all_sources = {
        "pubmed": fetch_pubmed,
        "europe_pmc": fetch_europe_pmc,
        "openalex": fetch_openalex,
        "crossref": fetch_crossref,
        "clinicaltrials": fetch_clinicaltrials,
        "biorxiv": fetch_biorxiv,
        "medrxiv": fetch_medrxiv,
        "semantic_scholar": fetch_semanticscholar,
        "scopus": fetch_scopus,
        "google_scholar": fetch_google_scholar,
        "arxiv": fetch_arxiv,
        "openaire": fetch_openaire,
        "core": fetch_core,
        "unpaywall": fetch_unpaywall,
        "f1000research": fetch_f1000research,
        "doaj": fetch_doaj,
    }
    
    sources = _resolve_sources(sources, list(all_sources.keys()))
    
    papers = []
    warnings = []
    
    for source_name in sources:
        if source_name not in all_sources:
            warnings.append(f"Unknown source: {source_name}")
            continue
        
        fetch_func = all_sources[source_name]
        try:
            results = fetch_func(effective_query, max_results)
            if not results and source_name in ["scopus", "google_scholar", "semantic_scholar", "core"]:
                if source_name == "semantic_scholar":
                    if not (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY")):
                        warnings.append("semantic_scholar skipped: API key not set")
                elif source_name == "google_scholar":
                    if not os.getenv("SERPAPI_API_KEY"):
                        warnings.append("google_scholar skipped: SERPAPI_API_KEY not set")
                elif source_name == "core":
                    if not os.getenv("CORE_API_KEY"):
                        warnings.append("core skipped: CORE_API_KEY not set")
                else:
                    api_key_var = f"{source_name.upper()}_API_KEY"
                    if not os.getenv(api_key_var):
                        warnings.append(f"{source_name} skipped: {api_key_var} not set")
            papers.extend(results)
        except Exception as e:
            warnings.append(f"{source_name} failed: {e}")
    
    # Deduplicate
    papers = _dedupe_papers(papers)
    
    # Score papers
    papers = [score_paper(p, effective_claim, hypothesis) for p in papers]
    papers.sort(key=lambda x: x.get("evidence_score", 0), reverse=True)

    data = {
        "query": query,
        "effective_query": effective_query,
        "claim": claim,
        "effective_claim": effective_claim,
        "hypothesis": hypothesis,
        "project_mode": project_mode,
        "query_expanded": expand,
        "count": len(papers),
        "warnings": warnings,
        "papers": papers,
    }

    return SearchResult(data)


def search_authors(
    query: str,
    author_aliases: Optional[List[str]] = None,
    affiliation: str = "",
    max_results: int = 5,
    publication_limit: int = 25,
    include_scival: bool = True,
) -> AuthorSearchResult:
    """Search author profiles via Scopus and enrich with SciVal metrics when available."""
    aliases = [query] + [a for a in (author_aliases or []) if a and a.strip()]
    warnings: List[str] = []
    found: Dict[str, Dict[str, Any]] = {}

    if not os.getenv("SCOPUS_API_KEY"):
        warnings.append("scopus author search skipped: API key not set")
    for alias in aliases:
        try:
            rows = search_scopus_authors(alias, limit=max_results, affiliation=affiliation)
        except Exception as e:
            warnings.append(f"scopus author search failed for {alias}: {e}")
            rows = []
        for row in rows:
            aid = str(row.get("author_id") or "").strip()
            if not aid:
                continue
            base = found.get(aid, {})
            merged = dict(base)
            merged.update({k: v for k, v in row.items() if v not in (None, "")})
            labels = [base.get("name"), row.get("name"), base.get("given_name"), row.get("given_name")]
            merged["alias_hits"] = _merge_unique_list(base.get("alias_hits") or [], [alias])
            merged["display_name"] = merged.get("display_name") or _best_author_label([x for x in labels if x]) or row.get("name")
            found[aid] = merged

    author_ids = list(found.keys())
    scival_lookup: Dict[str, Dict[str, Any]] = {}
    if include_scival and author_ids:
        raw = fetch_scival_author_metrics(author_ids)
        if not raw:
            warnings.append("scival metrics unavailable: missing entitlement, key, or no response")
        entries = raw.get("results") or raw.get("authors") or []
        if isinstance(entries, dict):
            entries = [entries]
        for item in entries:
            aid = str(item.get("author", {}).get("id") or item.get("id") or item.get("authorId") or "").strip()
            if not aid:
                continue
            metric_map: Dict[str, Any] = {}
            metrics = item.get("metrics") or item.get("metricTypes") or []
            if isinstance(metrics, dict):
                metrics = [metrics]
            for m in metrics:
                key = m.get("metricType") or m.get("name") or m.get("metric")
                value = m.get("valueByYear") or m.get("value") or m.get("currentValue")
                if isinstance(value, dict) and value:
                    try:
                        value = list(value.values())[-1]
                    except Exception:
                        pass
                metric_map[str(key)] = value
            # fallback if API returns flat fields
            for k in ["FieldWeightedCitationImpact", "ScholarlyOutput", "CitationsPerPublication", "ViewsCount"]:
                if k in item and k not in metric_map:
                    metric_map[k] = item.get(k)
            scival_lookup[aid] = metric_map

    authors: List[Dict[str, Any]] = []
    for aid, row in found.items():
        pubs = []
        try:
            pubs = fetch_scopus_author_publications(aid, publication_limit)
        except Exception as e:
            warnings.append(f"scopus publications failed for author {aid}: {e}")
        pubs = _dedupe_papers(pubs)
        pubs.sort(key=lambda x: (int(x.get("citations") or 0), int(x.get("year") or 0)), reverse=True)
        row["publication_count"] = len(pubs)
        row["top_publications"] = pubs[:5]
        row["scival"] = scival_lookup.get(aid, {})
        authors.append(row)

    authors.sort(
        key=lambda a: (
            float(a.get("scival", {}).get("FieldWeightedCitationImpact") or -1),
            int(a.get("document_count") or 0),
            int(a.get("citation_count") or 0),
        ),
        reverse=True,
    )

    return AuthorSearchResult({
        "query": query,
        "affiliation": affiliation,
        "count": len(authors),
        "warnings": warnings,
        "authors": authors,
    })


def _dedupe_key(p: Dict[str, Any]) -> tuple[str, str]:
    title = (p.get("title") or "").strip().lower()
    doi = (p.get("doi") or "").strip().lower()
    pid = (p.get("id") or "").strip().lower()
    if doi:
        return ("doi", doi)
    if title:
        return ("title", title)
    return ("id", pid)


def _merge_unique_list(a: Any, b: Any) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for item in (a or []):
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    for item in (b or []):
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _author_variants(name: str) -> List[tuple[str, str, str]]:
    raw = (name or "").strip()
    if not raw:
        return []
    cleaned = raw.replace(".", " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return []

    variants: List[tuple[str, str, str]] = []

    def build_variant(family: str, given: str) -> None:
        family = (family or "").strip()
        given = (given or "").strip()
        if not family:
            return
        family_key = family.lower()
        given_tokens = [t for t in given.split() if t]
        initials = "".join(t[0].lower() for t in given_tokens if t)
        canonical = f"{given} {family}".strip() if given else family
        item = (family_key, initials, canonical)
        if item not in variants:
            variants.append(item)

    if "," in cleaned:
        family, given = [x.strip() for x in cleaned.split(",", 1)]
        build_variant(family, given)
        return variants

    parts = cleaned.split()
    if len(parts) == 1:
        build_variant(parts[0], "")
        return variants

    if len(parts) == 2:
        left, right = parts
        # Heuristic priority for ambiguous two-token names.
        # Prefer interpretations where a 1-letter token is treated as given-name initial,
        # and the longer token is treated as family name.
        if len(right) == 1 and len(left) > 1:
            build_variant(left, right)   # Fujimura T -> family=Fujimura, given=T
            build_variant(right, left)
            return variants
        if len(left) == 1 and len(right) > 1:
            build_variant(right, left)   # A Bajetto -> family=Bajetto, given=A
            build_variant(left, right)
            return variants

    # Default western-style interpretation: given ... family
    build_variant(parts[-1], " ".join(parts[:-1]))

    # Fallback alternative for ambiguous two-token forms.
    if len(parts) == 2:
        build_variant(parts[0], parts[1])

    return variants


def _best_author_label(labels: List[str]) -> str:
    if not labels:
        return ""
    labels = [x.strip() for x in labels if x and x.strip()]
    if not labels:
        return ""
    # Prefer the longest label with at least one token longer than 1 char.
    labels.sort(key=lambda s: (
        any(len(tok) > 1 for tok in s.replace('.', ' ').split()),
        len(s),
    ), reverse=True)
    return labels[0]


def _merge_authors(a: Any, b: Any) -> List[str]:
    merged: Dict[tuple[str, str], List[str]] = {}
    order: List[tuple[str, str]] = []

    for item in list(a or []) + list(b or []):
        if not item:
            continue
        label = str(item).strip().replace('.', '')
        if not label:
            continue
        variants = _author_variants(label)
        if not variants:
            continue

        chosen_key = None
        for family_key, initials, _canonical in variants:
            key = (family_key, initials)
            if key in merged:
                chosen_key = key
                break

        if chosen_key is None:
            family_key, initials, _canonical = variants[0]
            chosen_key = (family_key, initials)
            merged[chosen_key] = []
            order.append(chosen_key)

        merged[chosen_key].append(label)

    return [_best_author_label(merged[k]) for k in order]


def _merge_paper_records(base: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged["source_hits"] = _merge_unique_list(base.get("source_hits") or [base.get("source")], new.get("source_hits") or [new.get("source")])
    merged["source_ids"] = _merge_unique_list(base.get("source_ids") or [base.get("id")], new.get("source_ids") or [new.get("id")])
    merged["authors"] = _merge_authors(base.get("authors"), new.get("authors"))

    for field in ["doi", "pmid", "pmcid", "url", "title", "id", "source"]:
        if not merged.get(field) and new.get(field):
            merged[field] = new.get(field)

    if not merged.get("abstract") and new.get("abstract"):
        merged["abstract"] = new.get("abstract")
    elif len((new.get("abstract") or "").strip()) > len((merged.get("abstract") or "").strip()):
        merged["abstract"] = new.get("abstract")

    try:
        merged["year"] = max(int(base.get("year") or 0), int(new.get("year") or 0)) or (base.get("year") or new.get("year"))
    except Exception:
        merged["year"] = base.get("year") or new.get("year")

    try:
        merged["citations"] = max(int(base.get("citations") or 0), int(new.get("citations") or 0))
    except Exception:
        merged["citations"] = base.get("citations") or new.get("citations") or 0

    return merged


def _dedupe_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge duplicate papers based on DOI, then title, then id."""
    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    order: List[tuple[str, str]] = []
    for p in papers:
        key = _dedupe_key(p)
        if key not in merged:
            item = dict(p)
            item["source_hits"] = item.get("source_hits") or ([item.get("source")] if item.get("source") else [])
            item["source_ids"] = item.get("source_ids") or ([item.get("id")] if item.get("id") else [])
            merged[key] = item
            order.append(key)
        else:
            merged[key] = _merge_paper_records(merged[key], p)
    return [merged[k] for k in order]
