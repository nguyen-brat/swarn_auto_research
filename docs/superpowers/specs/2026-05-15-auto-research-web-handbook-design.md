# Auto-Research Web Handbook — Design Spec

**Date:** 2026-05-15
**Author:** brainstorming session (Claude + user)
**Status:** Approved, ready for implementation plan

## Goal

Turn the markdown output of an auto-research run (`research_runs/<run>/14_chapters/` + `16_book/`) into a deployable, reader-friendly web handbook. The web layer must:

1. Render the existing grounded markdown without rewriting method-page prose.
2. Add web-native scannability (TLDR/key-idea callouts, inline diagrams, glossary tooltips, search, sidebar nav).
3. Rewrite only the seven book-level chapters (preface, motivating intro, goals, taxonomy, shared examples, eval outlook, glossary) for screen reading.
4. Reuse the hardened multi-agent SDK runner (sharded dispatch, retry, contract tests) to make generation fast and verifiable.
5. Produce one deployable site per research run and one umbrella site linking all runs.

## Non-Goals (v1)

- Auto cross-linking of bare method names in body prose (`cross-link-extractor`) — deferred to v2.
- Per-family comparison tables (`comparison-table-builder`) — deferred to v2.
- Reader features that need a server (comments, annotations, progress tracking) — site stays fully static.
- Re-running the research pipeline. Stage 19 only consumes existing artifacts.

## Decisions Locked in Brainstorming

| Decision | Choice |
|---|---|
| Deployment target | Static site via **Astro Starlight** |
| Rewrite scope | **Level 4** — render method pages as-is + augment with TLDR/callouts/glossary/diagrams; full web rewrite only for the 7 book-level chapters |
| Site organization | **Hybrid C** — one self-contained Starlight site per research run, plus an umbrella site at repo root linking them |
| Pipeline integration | **Both** — new Stage 19 in `run_auto_research.py` and a standalone `scripts/build_handbook.py`, both calling into a shared `handbook_builder/` module |
| v1 skills | `web-design-curator`, `web-tldr-writer`, `web-book-rewriter`, `diagram-author`, `glossary-builder`, `verification-web` |
| Visual style | **Developer-dark** — Tokyo Night palette, monospace headings, sans body, code-doc feel |

## Architecture

```
swarn_auto_research/
├── scripts/
│   ├── run_auto_research.py         # adds Stage 19 dispatch
│   └── build_handbook.py            # NEW, standalone; rebuilds web layer without rerunning research
├── handbook_builder/                 # NEW shared module
│   ├── __init__.py
│   ├── pipeline.py                  # stage entry; called by both scripts above
│   ├── dispatch.py                  # sharded fan-out, mirrors stage_14_chapter_writing
│   ├── scaffold.py                  # writes astro.config.mjs, package.json, theme CSS; copies templates/components/* into each run
│   ├── augment.py                   # per-page TLDR/callout/diagram splicing
│   ├── linker.py                    # rewrites internal links + sidebar.json → Starlight nav
│   ├── glossary.py                  # compiles tooltip dataset
│   ├── verify.py                    # verifier-web wrapper
│   └── templates/
│       └── components/              # static Astro components (Tldr/KeyIdea/Diagram/Term), copied verbatim into each run
├── .agents/skills/
│   ├── web-design-curator/SKILL.md
│   ├── web-tldr-writer/SKILL.md
│   ├── web-book-rewriter/SKILL.md
│   ├── diagram-author/SKILL.md
│   ├── glossary-builder/SKILL.md
│   └── verification-web/SKILL.md
├── .codex/                           # matching agent TOMLs
└── handbook/                         # NEW umbrella Starlight site indexing all runs
    └── astro.config.mjs

# Per research run:
research_runs/<run>/
└── 19_handbook/                      # NEW per-run Astro project
    ├── astro.config.mjs
    ├── package.json
    ├── src/content/docs/             # augmented copies of 14_chapters/**
    ├── src/assets/diagrams/          # generated Mermaid sources
    ├── public/glossary.json
    ├── .cache/manifest.json          # source-hash cache for idempotency
    └── dist/                         # `pnpm build` output, deploy-ready
```

Module boundaries:
- `handbook_builder/` is the only module that knows about Astro/Starlight. The rest of the system stays unaware of the web layer.
- Each skill takes pack/markdown in, returns strict JSON or MDX out. No agent reads sibling pages.
- `dispatch.py` reuses the hardened locked-CSV-write, traceback-capture, nested-`passed`-flag plumbing from the existing runner.

## Stage 19 Sub-Stages

| Sub-stage | Agent(s) | Calls | Workers | Output |
|---|---|---|---|---|
| 19.0 scaffold | `web-design-curator` | 1 | 1 | `astro.config.mjs`, theme CSS, `package.json`, base sidebar, `index.mdx` |
| 19.1 glossary | `glossary-builder` | 1 | 1 | `public/glossary.json` (terms not in `knowledge_base.md` get tooltips) |
| 19.2 diagrams | `diagram-author` | ~30 | 8 | `.mmd` per family chapter + per method-pack architecture sketch |
| 19.3 augment methods | `web-tldr-writer` + `verification-web` | ~150 | 12 | per-page `{tldr, key_idea, when_to_use, tags}` JSON, gated by verifier |
| 19.4 rewrite book | `web-book-rewriter` + `verification-web` | 7 | 7 | MDX rewrites for preface/intro/goals/taxonomy/shared-examples/eval-outlook/glossary |
| 19.5 assemble + build | in-process, no agent | — | — | splice MDX, rewrite sidebar, run `pnpm install && pnpm build` → `dist/` |

Wall-time budget: **~12 minutes** total. 19.3 dominates (~7 min at 12 workers).

## Agent Contracts

### `web-design-curator` (one-shot scaffold)
- **Input:** run config (topic, run id, chapter manifest), theme = Tokyo Night.
- **Output (strict JSON):**
  ```json
  {
    "astro_config": "<full astro.config.mjs>",
    "theme_css": "<custom.css overrides>",
    "package_json": {...},
    "sidebar_items": [...],
    "home_page_mdx": "<index.mdx with hero + part jump-cards>"
  }
  ```
- **Hard rules:** `starlight()` + `expressiveCode` plugins present; sidebar covers every file in `14_chapters/`; package.json pins exact versions.
- **Static assets (not agent-generated):** the four reusable Astro components (`src/components/Tldr.astro`, `KeyIdea.astro`, `Diagram.astro`, `Term.astro`) live in the repo under `handbook_builder/templates/components/` and are **copied verbatim** by `scaffold.py` into each run's `19_handbook/src/components/`. They are part of the codebase, version-controlled, not regenerated per run. The agent does not author them.

### `web-tldr-writer` (per method page, sharded)
- **Input:** method-page markdown + its chapter_pack JSON + glossary.
- **Output (strict JSON):**
  ```json
  {
    "tldr": "<2–4 sentences, ≤ 280 chars>",
    "key_idea": "<1 sentence, ≤ 140 chars>",
    "when_to_use": ["<bullet>", "<bullet>"],
    "tags": ["TTS", "Non-AR"]
  }
  ```
- **Hard rules:**
  - Every claim must appear in source markdown OR the pack. No new method names. No new metrics.
  - Tags drawn from `tags_vocab.json` only.

### `web-book-rewriter` (per book chapter, 7 total)
- **Input:** original book chapter markdown + book context (topic, taxonomy).
- **Output:** MDX content string.
- **Hard rules:** paragraphs ≤ 4 sentences; h3 every ~200 words; Starlight `:::tip` / `:::note` for takeaways; `<details>` for asides; preserve every internal link and citation; no new factual claims (verifier gates).

### `diagram-author` (per family + per method-pack)
- **Input:** taxonomy JSON for family / chapter_pack JSON for method.
- **Output:** one `.mmd` per artifact (Mermaid source).
- **Hard rules:** every node label traces to a name in input JSON; `mmdc --dry-run` parse check on every file.

### `glossary-builder` (one-shot)
- **Input:** all method packs + `.agents/knowledge_base.md`.
- **Output:**
  ```json
  [{"term": "...", "definition": "...", "appears_in": ["page1"], "kb_known": false}]
  ```
- **Hard rules:** `kb_known: true` entries emitted but not rendered as tooltips (already known to user); every `<Term name="X">` reference in any MDX must resolve.

### `verification-web` (gate for 19.3 and 19.4)
- **Input:** original chapter markdown + candidate augmented MDX/JSON.
- **Output:** `{passed: bool, claims: [...], rejection_reason: "..."}` — top-level `passed` flag (matches the runner fix already shipped).
- **Hard rules:** any claim not in original → `partially_supported` or worse → fail → augmentation discarded, page falls back to original markdown.

## Reader-Facing Surface

### Method page

```mdx
---
title: "MaskGCT"
description: "Zero-Shot TTS with Masked Generative Codec Transformer"
tags: ["TTS", "Non-AR"]
sidebar:
  label: "MaskGCT (vq-vae-semantic-discretization)"
---

import Tldr from '../../components/Tldr.astro';
import KeyIdea from '../../components/KeyIdea.astro';
import Diagram from '../../components/Diagram.astro';
import Term from '../../components/Term.astro';

<Tldr>Non-autoregressive masked codec transformer for zero-shot TTS — no phoneme alignment.</Tldr>

<KeyIdea>Predict masked codec tokens in parallel, then iteratively unmask with a confidence schedule.</KeyIdea>

:::tip[When to use this]
- Zero-shot speaker cloning without phoneme alignment.
- Latency-sensitive: ≤10 unmasking steps.
- Existing <Term name="RVQ">residual VQ</Term> codec available.
:::

<Diagram src="../../assets/diagrams/maskgct.mmd" />

## Architecture

<!-- ORIGINAL CHAPTER PROSE — UNCHANGED -->
...
```

### Book chapter

```mdx
---
title: "Method Taxonomy"
sidebar: { order: 4 }
---

import Diagram from '../../components/Diagram.astro';

The field splits along three axes: ...

## Generation models

...

<Diagram src="../../assets/diagrams/taxonomy.mmd" />

### Codec-based vs continuous

<details>
<summary>Why both exist</summary>
Codec models won on streaming...
</details>
```

### Sidebar and navigation

- Generated from `16_book/sidebar.json` (display labels already in place).
- Three top-level groups: **Book**, **Part 1: Generation**, **Part 2: Interaction** (or whatever `chapters_manifest.json` declares).
- Search is Starlight's built-in pagefind (zero-config, full-text).

### Theme

- Tokyo Night palette via `custom.css` overrides on Starlight's dark base.
- Headings: `JetBrains Mono`; body: `Inter`; code: `JetBrains Mono`.
- `<Tldr>` = green-accent border-left card; `<KeyIdea>` = blue-accent card; `<Term>` = dotted underline with hover popover sourced from `glossary.json`.
- Top-right chrome: theme toggle, GitHub link, search.

### Umbrella site (`handbook/`)

- Single Starlight project at repo root.
- One card per run (grid layout) linking to the run's deployed URL or local path.
- Regenerated by `web-design-curator` whenever a new `research_runs/*/run_config.json` appears.

### `NEEDS_REVIEW.md`

Reuses the existing pattern. Any page where `verification-web` rejected the augmentation → original markdown rendered + page listed here with rejection reason and the rejected payload.

## Testing

New files under `tests/`:

```
tests/
├── test_handbook_scaffold.py         # web-design-curator prompt-text contract
├── test_handbook_tldr.py             # web-tldr-writer schema contract
├── test_handbook_book_rewriter.py    # web-book-rewriter contract
├── test_handbook_diagram.py          # mmd parse + node provenance
├── test_handbook_glossary.py         # schema + kb_known flag
├── test_handbook_verifier_web.py     # top-level passed flag, rejection cases
├── test_handbook_pipeline.py         # end-to-end stage on a 3-page fixture run
└── test_handbook_assemble.py         # MDX splicing, link rewriting, sidebar build
```

Conventions match the existing suite:
- **Prompt-text contract tests** assert SKILL.md contains the rule strings (e.g., "MUST be grounded in the pack").
- **Schema validation** on every agent JSON output.
- **No real Codex calls** in tests — mock the SDK at the `dispatch.py` seam.
- A small `tests/fixtures/handbook_mini_run/` with 3 method pages, 1 family chapter, 1 book chapter feeds the end-to-end test.

Target: full `pytest tests/` stays under 30s. New stage tests add ~5s.

## Performance and Caching

- `19_handbook/.cache/manifest.json` stores `{source_path: sha256}` per page.
- Re-run skips pages whose source markdown is unchanged.
- Diagrams cached by pack-hash.
- `--rebuild-all` forces full regeneration. `--rebuild-scaffold` regenerates scaffold + umbrella only.
- `pnpm build` for ~150 MDX pages: ~30–60s cold, ~10s warm (Astro's incremental).

## Rollout Plan

Five independently shippable milestones:

1. **M0 — scaffold only.** Static Starlight site renders existing markdown as-is. One agent (`web-design-curator`). Verify pnpm build, sidebar, search.
2. **M1 — glossary + diagrams.** Add `glossary-builder` + `diagram-author`. Tooltips and inline Mermaid land.
3. **M2 — method-page augmentation.** Add `web-tldr-writer` + `verification-web` for ~150 method pages.
4. **M3 — book-chapter rewrite.** Add `web-book-rewriter` (+ verifier) for the 7 book chapters.
5. **M4 — umbrella site + deployment docs.** Repo-level `handbook/` + GitHub Pages workflow.

Each milestone produces a usable handbook. Tests for that milestone's skills land with the milestone.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `web-tldr-writer` hallucinates method names (regression of the bug we just fixed) | `verification-web` gates every page; reject → original markdown passes through; pack-only naming rule in SKILL.md |
| Mermaid diagrams reference nodes absent from source pack | `diagram-author` contract: every node label must appear in input JSON; CI parse-check with `mmdc --dry-run` |
| Theme/CSS drift across milestones | `web-design-curator` is one-shot per scaffold; CSS pinned in repo, not regenerated each run unless `--rebuild-scaffold` |
| 150-page Codex shard exhausts retries | Reuses hardened retry (max_attempts=6, traceback capture); failures fall back to unaugmented page and log to `NEEDS_REVIEW.md` |
| Starlight major-version upgrade breaks build | Pin exact versions in `package.json`; lockfile committed; bump explicitly with a separate PR |
| Knowledge graph terms duplicated in glossary (`kb_known` already covers it but render path may miss flag) | Single source of truth: `<Term>` component reads `glossary.json` and renders nothing when `kb_known: true` |

## Open Questions

None at design approval time. Implementation plan will surface lower-level details (exact Starlight component file layout, `dispatch.py` reuse points, fixture content).

## Next Step

Invoke `writing-plans` to produce the implementation plan covering milestones M0–M4 with concrete tasks, file diffs, and contract tests.
