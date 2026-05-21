# Swarn Auto Research

This repository now has two layers:

1. A standalone MCP server for paper discovery and section-level reading.
2. A repo-scoped Codex scaffold for multi-agent, file-based AI paper research.

## Tools

- `bulk_normal_start_search`: Runs broad paper discovery for topic queries, filters the result, saves the selected arXiv-id-to-abstract JSON file, and returns the selected papers plus the output path.
- `get_paper_markdown`: Fetches the full Markdown content for an arXiv paper by arXiv ID.
- `get_paper_section`: Fetches an arXiv paper and returns one Markdown section. Nested sections use slash-separated paths such as `Model Architecture/Encoder and Decoder Stacks/Encoder:`.

## Research Workflow Scaffold

The MVP scaffold (see `docs/superpowers/specs/2026-05-08-auto-research-mvp-design.md`) lives entirely in config files:

- `.agents/skills/auto-research-orchestrator/SKILL.md` — the main pipeline.
- `.agents/skills/<name>/SKILL.md` — per-stage skills (knowledge-base-reading, weak-evidence-extraction, weak-graph-extraction, knowledge-gap-detection, paper-pool-expansion, pageindex-building, chapter-writing, verification).
- `.codex/agents/*.toml` — narrow Codex subagents that load the matching skill.
- `.codex/config.toml` — registers the local MCP server and MVP budgets.
- `.agents/knowledge_base.md` — the user's known-concepts list. Edit by hand.

A run produces files only under `research_runs/{topic_slug}-{timestamp}/`. The shared knowledge base is read-only during a run; any concepts that recurred but were not in the KB land in `17_learning_suggestions/knowledge_to_add.md` for the user to review.

## Run Locally

```bash
uv sync
uv run swarn-auto-research-mcp
```

You can also run the server directly:

```bash
python -m swarn_research_mcp.server
```

## Register With Codex

From this repository:

```bash
codex mcp add swarn-auto-research -- uv run swarn-auto-research-mcp
```

## Run The Scaffold

Use Codex from this repository so the project-scoped config and agents load:

```bash
codex
```

Codex picks up `.codex/config.toml` automatically, which registers the local MCP server and MVP configuration.

Key files:

- `.codex/config.toml` for MCP registration and agent limits
- `.codex/agents/*.toml` for custom subagent roles
- `.agents/skills/auto-research-orchestrator/SKILL.md` for the orchestration workflow
- `.agents/knowledge_base.md` for the user's known-concepts list

## Web Handbook

Stage 19 builds a per-run Astro Starlight handbook from the completed Markdown book artifacts.
The default Stage 19 milestone is `M0`, which creates the base site and copies grounded chapters:

```bash
HANDBOOK_SKIP_PNPM=1 env PYTHONPATH=. python scripts/run_auto_research.py \
  --run-id <run_id> --phase write --resume --from-stage 19
```

For the full augmented handbook with glossary, diagrams, method TLDRs, and rewritten book-level pages, run:

```bash
HANDBOOK_MILESTONE=M3 env PYTHONPATH=. python scripts/build_handbook.py research_runs/<run_id>/ --skip-pnpm
```

This produces the source site under `research_runs/<run_id>/19_handbook/`. Omit `--skip-pnpm` when Node and pnpm are available and you want the static build in `19_handbook/dist/`.
