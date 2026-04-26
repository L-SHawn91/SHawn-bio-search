"""Capability registry: which source chains satisfy which retrieval intent.

A *capability* is a named retrieval intent like ``paper.by_keywords`` or
``citation.verify``. Each capability owns an ordered fallback chain of
:class:`SourceStep`s; the runner walks the chain top-to-bottom and stops at
the first step whose result satisfies the capability's ``success_predicate``.

PR B seeds two capabilities (``paper.by_keywords`` and ``paper.by_doi``).
Additional capabilities (``citation.verify``, ``dataset.by_keyword``,
``oa_pdf.by_doi``, ``paper.by_pmid``, ``paper.by_title``, ``paper.by_author``)
are added in follow-up PRs. The registry is open: any module can call
:func:`register` to add or replace a capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

# Late imports inside fetcher lambdas keep the orchestrator import-light and
# break the cycle that would otherwise form via shawn_bio_search.search →
# orchestrator → search.

Args = Mapping[str, Any]
Records = Sequence[Dict[str, Any]]
Fetcher = Callable[[Args], Records]
Predicate = Callable[[Records, Args], bool]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceStep:
    """One link in a capability's fallback chain."""

    source: str
    fetcher: Fetcher
    why: str = ""
    timeout_s: float = 30.0


@dataclass(frozen=True)
class Capability:
    """A retrieval intent with an ordered fallback chain."""

    name: str
    chain: Tuple[SourceStep, ...]
    success_predicate: Predicate = field(
        default=lambda records, _args: bool(records)
    )
    description: str = ""

    def __post_init__(self) -> None:
        if not self.chain:
            raise ValueError(f"Capability {self.name!r} must have at least one step")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Capability] = {}


def register(cap: Capability, *, replace: bool = False) -> None:
    """Add or replace a capability in the registry."""
    if cap.name in _REGISTRY and not replace:
        raise ValueError(f"Capability {cap.name!r} already registered; pass replace=True")
    _REGISTRY[cap.name] = cap


def get(name: str) -> Capability:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown capability {name!r}; registered: {sorted(_REGISTRY)}"
        ) from exc


def list_capabilities() -> Tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def clear_registry() -> None:
    """Test helper: wipe all registrations."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Built-in fetcher adapters
# ---------------------------------------------------------------------------


def _kw(args: Args) -> Tuple[str, int]:
    """Extract (query, limit) from capability args, with sensible defaults."""
    query = args.get("query") or args.get("q") or ""
    limit = int(args.get("max_results") or args.get("limit") or 10)
    return str(query), max(1, limit)


def _adapter_by_keywords(source_module: str, fn_name: str) -> Fetcher:
    """Build a fetcher that calls ``source_module.fn_name(query, limit)``."""

    def _call(args: Args) -> Records:
        from importlib import import_module

        module = import_module(f"shawn_bio_search.sources.{source_module}")
        fn = getattr(module, fn_name)
        query, limit = _kw(args)
        return list(fn(query, limit))

    _call.__name__ = f"_kw_adapter_{source_module}"
    return _call


def _adapter_pubmed_by_doi() -> Fetcher:
    def _call(args: Args) -> Records:
        from shawn_bio_search.sources.pubmed import fetch_by_doi

        doi = (args.get("doi") or "").strip()
        if not doi:
            return []
        return list(fetch_by_doi(doi))

    return _call


def _adapter_doi_query(source_module: str, fn_name: str, prefix: str) -> Fetcher:
    """For sources that accept DOI as a free-text query (Crossref, OpenAlex,
    Europe PMC). ``prefix`` is the field tag the source expects, e.g. ``doi:``
    or ``DOI:``.
    """

    def _call(args: Args) -> Records:
        from importlib import import_module

        module = import_module(f"shawn_bio_search.sources.{source_module}")
        fn = getattr(module, fn_name)
        doi = (args.get("doi") or "").strip()
        if not doi:
            return []
        query = f"{prefix}{doi}"
        limit = int(args.get("max_results") or 5)
        return list(fn(query, limit))

    return _call


# ---------------------------------------------------------------------------
# Built-in capabilities (seed for PR B)
# ---------------------------------------------------------------------------


def _seed_paper_by_keywords() -> Capability:
    return Capability(
        name="paper.by_keywords",
        chain=(
            SourceStep(
                "pubmed",
                _adapter_by_keywords("pubmed", "fetch_pubmed"),
                why="strongest MeSH-indexed biomedical signal",
            ),
            SourceStep(
                "europe_pmc",
                _adapter_by_keywords("europe_pmc", "fetch_europe_pmc"),
                why="broader life-sci coverage including preprints",
            ),
            SourceStep(
                "openalex",
                _adapter_by_keywords("openalex", "fetch_openalex"),
                why="cross-disciplinary metadata coverage",
            ),
            SourceStep(
                "arxiv",
                _adapter_by_keywords("arxiv", "fetch_arxiv"),
                why="physics/CS preprints absent from biomed indices",
            ),
            SourceStep(
                "biorxiv",
                _adapter_by_keywords("biorxiv", "fetch_biorxiv"),
                why="recent bio preprints not yet in Europe PMC",
            ),
            SourceStep(
                "medrxiv",
                _adapter_by_keywords("medrxiv", "fetch_medrxiv"),
                why="recent clinical preprints not yet in Europe PMC",
            ),
        ),
        description="Free-text keyword search for papers (sequential fallback).",
    )


def _seed_paper_by_doi() -> Capability:
    return Capability(
        name="paper.by_doi",
        chain=(
            SourceStep(
                "crossref",
                _adapter_doi_query("crossref", "fetch_crossref", "doi:"),
                why="DOI registration authority",
            ),
            SourceStep(
                "openalex",
                _adapter_doi_query("openalex", "fetch_openalex", "doi:"),
                why="full metadata + open-access status",
            ),
            SourceStep(
                "europe_pmc",
                _adapter_doi_query("europe_pmc", "fetch_europe_pmc", "DOI:"),
                why="biomedical full-text fallback",
            ),
            SourceStep(
                "pubmed",
                _adapter_pubmed_by_doi(),
                why="PMID linkage via dedicated DOI lookup endpoint",
            ),
        ),
        description="Single-paper lookup by DOI (sequential fallback).",
    )


def _install_seed_capabilities() -> None:
    """Idempotent seed; safe to call multiple times."""
    seeds = [_seed_paper_by_keywords(), _seed_paper_by_doi()]
    for cap in seeds:
        if cap.name in _REGISTRY:
            continue
        _REGISTRY[cap.name] = cap


_install_seed_capabilities()


# ---------------------------------------------------------------------------
# Status mapping helpers used by the runner
# ---------------------------------------------------------------------------


def missing_required_keys(source: str) -> Tuple[str, ...]:
    """Return env var names that would unblock ``source``, or () if ready.

    Mirrors the policy of :data:`shawn_bio_search.sources.KEYED_SOURCES`:
    a source is ready when *at least one* of its listed env vars is set.
    """
    import os

    from shawn_bio_search.sources import KEYED_SOURCES

    needed = KEYED_SOURCES.get(source, [])
    if not needed:
        return ()
    if any(os.environ.get(name) for name in needed):
        return ()
    return tuple(needed)
