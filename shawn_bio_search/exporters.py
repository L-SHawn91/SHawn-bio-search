"""Citation export formats: BibTeX, RIS, CSL-JSON.

Dependency-free generators that take the normalized paper records emitted by
`search_papers()` (each one a `dict` with the standard keys: `title`, `authors`,
`year`, `doi`, `pmid`, `journal`, `abstract`, `url`, optional `citation_key`)
and emit citation-manager-compatible strings.

Why no external library:
- `bibtexparser` and `rispy` are both heavier than the 60-line emitters here.
- The output is always-in-our-control text, not parsed-then-rewritten.
- Keeps the package zero-dependency on the runtime path.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

_NON_KEY_CHARS = re.compile(r"[^A-Za-z0-9]+")


def _slugify(text: str, max_len: int = 24) -> str:
    cleaned = _NON_KEY_CHARS.sub("", text or "").lower()
    return cleaned[:max_len]


def _looks_like_initials(token: str) -> bool:
    return bool(token) and len(token) <= 4 and token.isalpha() and token.isupper()


def _first_author_surname(authors: Any) -> str:
    if not authors:
        return ""
    first = authors[0] if isinstance(authors, list) else str(authors)
    if isinstance(first, dict):
        first = first.get("name") or first.get("family") or ""
    if "," in first:
        return first.split(",", 1)[0].strip()
    parts = first.strip().split()
    if not parts:
        return ""
    if len(parts) >= 2 and _looks_like_initials(parts[-1]):
        return " ".join(parts[:-1])
    return parts[-1]


def _first_title_word(title: str) -> str:
    if not title:
        return ""
    for word in title.split():
        cleaned = _NON_KEY_CHARS.sub("", word)
        if len(cleaned) >= 3:
            return cleaned.lower()
    return ""


def citation_key(paper: Dict[str, Any]) -> str:
    """Stable per-paper citation key. Falls back to `surname+year+firstword`."""
    explicit = paper.get("citation_key")
    if explicit:
        return _NON_KEY_CHARS.sub("_", str(explicit)).strip("_")
    surname = _slugify(_first_author_surname(paper.get("authors", [])), 16)
    year = str(paper.get("year") or "")
    word = _slugify(_first_title_word(paper.get("title", "")), 12)
    parts = [p for p in (surname, year, word) if p]
    return "_".join(parts) or "untitled"


def _split_author(name: Any) -> Dict[str, str]:
    """Best-effort split of an author string into family/given."""
    if isinstance(name, dict):
        return {
            "family": str(name.get("family") or name.get("name") or "").strip(),
            "given": str(name.get("given") or "").strip(),
        }
    s = str(name or "").strip()
    if "," in s:
        family, _, given = s.partition(",")
        return {"family": family.strip(), "given": given.strip()}
    parts = s.split()
    if len(parts) <= 1:
        return {"family": s, "given": ""}
    if _looks_like_initials(parts[-1]):
        return {"family": " ".join(parts[:-1]), "given": parts[-1]}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def _bibtex_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def to_bibtex(papers: Iterable[Dict[str, Any]]) -> str:
    """Render a list of papers as BibTeX entries (one `@article` per paper)."""
    entries: List[str] = []
    for paper in papers:
        key = citation_key(paper)
        authors = paper.get("authors") or []
        if isinstance(authors, list):
            author_field = " and ".join(
                str(a.get("name") if isinstance(a, dict) else a) for a in authors if a
            )
        else:
            author_field = str(authors)
        fields = [
            ("author", author_field),
            ("title", paper.get("title", "")),
            ("journal", paper.get("journal", "")),
            ("year", paper.get("year", "")),
            ("doi", paper.get("doi", "")),
            ("pmid", paper.get("pmid", "")),
            ("url", paper.get("url", "")),
            ("abstract", paper.get("abstract", "")),
        ]
        body_lines = [
            f"  {name} = {{{_bibtex_escape(value)}}},"
            for name, value in fields
            if value not in (None, "", 0)
        ]
        entries.append("@article{" + key + ",\n" + "\n".join(body_lines) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")


_RIS_TAG_ORDER = ["TY", "AU", "TI", "T2", "JO", "PY", "DO", "UR", "AB", "ID", "ER"]


def to_ris(papers: Iterable[Dict[str, Any]]) -> str:
    """Render a list of papers in RIS format (one record per paper)."""
    chunks: List[str] = []
    for paper in papers:
        record: Dict[str, List[str]] = {tag: [] for tag in _RIS_TAG_ORDER}
        record["TY"].append("JOUR")
        for author in paper.get("authors") or []:
            name = author.get("name") if isinstance(author, dict) else author
            if name:
                record["AU"].append(str(name))
        if paper.get("title"):
            record["TI"].append(str(paper["title"]))
        if paper.get("journal"):
            record["JO"].append(str(paper["journal"]))
            record["T2"].append(str(paper["journal"]))
        if paper.get("year"):
            record["PY"].append(str(paper["year"]))
        if paper.get("doi"):
            record["DO"].append(str(paper["doi"]))
        if paper.get("url"):
            record["UR"].append(str(paper["url"]))
        if paper.get("abstract"):
            record["AB"].append(str(paper["abstract"]))
        record["ID"].append(citation_key(paper))
        record["ER"].append("")
        lines: List[str] = []
        for tag in _RIS_TAG_ORDER:
            for value in record[tag]:
                lines.append(f"{tag}  - {value}".rstrip())
        chunks.append("\n".join(lines))
    return ("\n\n".join(chunks) + "\n") if chunks else ""


def to_csl_json(papers: Iterable[Dict[str, Any]]) -> str:
    """Render a list of papers as a CSL-JSON array (Zotero / Pandoc compatible)."""
    items: List[Dict[str, Any]] = []
    for paper in papers:
        item: Dict[str, Any] = {
            "id": citation_key(paper),
            "type": "article-journal",
        }
        title = paper.get("title")
        if title:
            item["title"] = str(title)
        authors = [
            _split_author(a) for a in (paper.get("authors") or []) if a
        ]
        if authors:
            item["author"] = authors
        if paper.get("journal"):
            item["container-title"] = str(paper["journal"])
        if paper.get("year"):
            try:
                item["issued"] = {"date-parts": [[int(paper["year"])]]}
            except (TypeError, ValueError):
                pass
        if paper.get("doi"):
            item["DOI"] = str(paper["doi"])
        if paper.get("pmid"):
            item["PMID"] = str(paper["pmid"])
        if paper.get("url"):
            item["URL"] = str(paper["url"])
        if paper.get("abstract"):
            item["abstract"] = str(paper["abstract"])
        items.append(item)
    return json.dumps(items, indent=2, ensure_ascii=False)
