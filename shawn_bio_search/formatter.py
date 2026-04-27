"""Output formatting module for search results."""
from __future__ import annotations

from typing import Any, Dict, List


def format_results(papers: List[Dict[str, Any]], fmt: str = "plain", top_n: int = 10) -> str:
    """Format papers to specified output format.
    
    Args:
        papers: List of paper dictionaries
        fmt: Output format - "plain", "markdown", or "json"
        top_n: Number of top results to include
    
    Returns:
        Formatted string
    """
    papers = papers[:top_n]
    
    if fmt == "json":
        return _format_json(papers)
    elif fmt == "markdown":
        return _format_markdown(papers)
    else:  # plain
        return _format_plain(papers)


def _format_plain(papers: List[Dict[str, Any]]) -> str:
    """Format as plain text."""
    lines = []
    for p in papers:
        source = p.get("source", "unknown")
        authors = ", ".join(p.get("authors", [])[:3])
        if len(p.get("authors", [])) > 3:
            authors += " et al."
        year = p.get("year", "")
        title = p.get("title", "")
        doi = p.get("doi", "")
        
        # Include evidence score if present
        evidence = p.get("evidence_score")
        llm_relevance = p.get("llm_relevance")
        if evidence is not None:
            line = f"[{source}] Evidence: {evidence:.2f}"
            if llm_relevance is not None:
                line += f" | LLM: {float(llm_relevance):.2f} {p.get('llm_direction') or ''}".rstrip()
            line += f" | {authors} ({year}). {title}. DOI: {doi}"
            if llm_relevance is not None and p.get("llm_risk"):
                line += f" | Risk: {p.get('llm_risk')}"
            lines.append(line)
        else:
            lines.append(f"[{source}] {authors} ({year}). {title}. DOI: {doi}")
    
    return "\n\n".join(lines)


def _format_markdown(papers: List[Dict[str, Any]]) -> str:
    """Format as Markdown."""
    has_llm = any(p.get("llm_relevance") is not None for p in papers)
    if has_llm:
        lines = [
            "| Source | Year | Authors | Title | Evidence | LLM | Direction | DOI |",
            "|--------|------|---------|-------|---------:|----:|-----------|-----|",
        ]
    else:
        lines = ["| Source | Year | Authors | Title | DOI |", "|--------|------|---------|-------|-----|"]
    
    for p in papers:
        source = p.get("source", "")
        year = str(p.get("year", ""))
        authors = ", ".join(p.get("authors", [])[:2])
        if len(p.get("authors", [])) > 2:
            authors += " et al."
        title = p.get("title", "")[:60] + "..." if len(p.get("title", "")) > 60 else p.get("title", "")
        doi = p.get("doi", "")
        doi_link = f"[{doi}](https://doi.org/{doi})" if doi else ""
        if has_llm:
            evidence = p.get("evidence_score")
            llm = p.get("llm_relevance")
            evidence_text = f"{float(evidence):.2f}" if evidence is not None else ""
            llm_text = f"{float(llm):.2f}" if llm is not None else ""
            direction = p.get("llm_direction") or ""
            lines.append(f"| {source} | {year} | {authors} | {title} | {evidence_text} | {llm_text} | {direction} | {doi_link} |")
        else:
            lines.append(f"| {source} | {year} | {authors} | {title} | {doi_link} |")
    
    return "\n".join(lines)


def _format_json(papers: List[Dict[str, Any]]) -> str:
    """Format as JSON string."""
    import json
    return json.dumps({"papers": papers, "count": len(papers)}, indent=2, ensure_ascii=False)
