# Agent Compatibility

`SHawn-bio-search` is a portable SHawn ecosystem skill. The canonical contract is the repo-root `SKILL.md`.

## Policy

- Do not deploy this skill through symlinks.
- Use direct repo paths or copied adapter files.
- Keep `SKILL.md` as the source of truth for activation rules.
- Keep `AGENTS.md` and `CLAUDE.md` as environment-specific supplements, not competing contracts.

## Environment Mapping

| Environment | Entry point | Notes |
|---|---|---|
| OpenClaw | repo root `SKILL.md` | Configure `skills.load.extraDirs` to include `~/github/SHawn-bio-search`. |
| Claude Code | `SKILL.md`, then `CLAUDE.md` | `CLAUDE.md` keeps Claude-specific examples and defaults. |
| Codex/agent runtimes | `SKILL.md`, then `AGENTS.md` | `AGENTS.md` is the vendor-neutral agent handoff. |
| Ollama/local LLM | `SKILL.md` as system/context prompt | Ollama has no native skill loader; pass this file into the prompt or wrapper. |
| Shell/Python | `pyproject.toml` entry points | Use `shawn-bio-search`, `sbs`, and `shawn-bio-download`. |

## Canonical Paths

Prefer home-relative paths so Linux and macOS can share the same rule:

```text
~/github/SHawn-bio-search
```

Use `SHAWN_BIO_SEARCH_HOME` only when the repo is intentionally elsewhere.

## Integration Boundary

`SHawn-bio-search` owns retrieval, verification, access enrichment, and retrieval bundles.

It does not own:
- persistent paper corpus databases
- heavy bioinformatics analysis
- manuscript writing
- vault organization

Those are downstream SHawn ecosystem responsibilities.
