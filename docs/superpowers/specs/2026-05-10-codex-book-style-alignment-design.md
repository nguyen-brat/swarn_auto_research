# Codex Pipeline — Book_style Alignment & SDK Session Migration

**Date:** 2026-05-10
**Scope:** Skills/pipeline only. No retroactive fix to existing research runs.
**Trigger:** Audit of `research_runs/voice-language-model-text-speech-io-20260509-222749` against `Book_style.md` surfaced seven structural gaps.

---

## Goals

1. Bring the auto-research pipeline's output into structural agreement with `Book_style.md`.
2. Reduce orchestrator context burden by routing single-shot stages through the Codex SDK session API instead of full sub-agent dispatch.
3. Make verification a hard quality gate so unverified chapters cannot reach the published book.

## Non-goals

- Retroactively fixing the existing voice-LM run.
- Changing pack-building (stage 13) — it already supplies the right material; only the writers were mislabeling it.
- Changing per-agent model/temperature config in `.toml` files beyond the five being deleted.
- Adding new evaluation metrics or UI surfaces.

---

## Section 1 — Topic-adaptive parts in `outline.json`

### Problem
`Book_style.md` mandates a Part 1–5 grouping (interpretable / local / global / model-specific / evaluation). The pipeline emits a flat list of families with no part assignment, so `SUMMARY.md` and `04_method_taxonomy.md` cannot group by part.

### Change
`taxonomy-building` SKILL gains a new step after community labeling: emit a `parts` array.

```json
"parts": [
  {"id": "representation_and_tokenization", "title": "Representation and Tokenization",
   "family_ids": ["multi_codebook_speech_generation", "..."]}
]
```

### Rules
- Default labels are Book_style's five (`interpretable`, `local`, `global`, `model_specific`, `evaluation_outlook`).
- The skill MAY rename, merge, or drop default parts based on topic fit, subject to:
  - `2 ≤ len(parts) ≤ 5`
  - Every family appears in exactly one part.
  - Every part has `≥ 1` family.
- Self-validate before writing `outline.json`.

### Downstream
- Stage 14 `book-section-writing` for `04_method_taxonomy.md` reads `parts` and emits one `##` heading per part.
- Stage 18 reads `parts` and groups SUMMARY accordingly.

---

## Section 2 — Singleton merge

### Problem
The voice-LM run produced ~25 single-method families (NeuFA, HuBERT, TiCodec, IndexTTS2, BASE TTS, Pheme, …). They function as method chapters wearing family hats. `Book_style.md` treats families as "main method families," not paper wrappers.

### Change
After community clustering and labeling, but before writing `outline.json`, the taxonomy step **merges every singleton family into its nearest non-singleton family**.

### Algorithm
1. Identify all families with `len(method_ids) == 1`.
2. For each singleton, find the nearest non-singleton family by:
   - **Primary:** count of shared verified-graph edges between the singleton's method and the candidate family's methods.
   - **Tiebreaker:** intersection of `neighbor_method_ids`.
3. Merge: append the method to the target family's `method_ids`; the target keeps its title and ID.
4. If no non-singleton candidate has any graph connection, place the method into a catch-all family named after its part (e.g. `other_evaluation_methods`). One catch-all per part is allowed.

### Hard rule
- After merge, every family must satisfy `len(method_ids) ≥ 2`.
- Self-validation rejects outlines that don't.

---

## Section 3 — Family chapter headings re-anchored to Book_style

### Problem
`family-chapter-writing` SKILL prescribes `What this family is / Core design pattern / When this family is useful / Methods in this family / Comparison / How this family compares to others / Boundary cases and overlaps`. `Book_style.md` prescribes a different 10-section template. Skill contradicts the canonical style guide.

### Change
Replace the seven-section list in `family-chapter-writing` SKILL with `Book_style.md`'s 10:

1. `## Summary`
2. `## Motivation`
3. `## Core Idea`
4. `## Common Pipeline`
5. `## Main Variants`
6. `## Representative Methods`
7. `## Strengths`
8. `## Limitations`
9. `## When to Use`
10. `## Related Families`

### Preserved value-adds
- The required **comparison table** (one row per method, columns: Method / Core mechanism / When it helps / When it hurts / Cite) is now an artifact *inside* `## Main Variants`. Hard rule: section must contain a table with header row matching that schema and one row per method.
- The bulleted method-link list lives in `## Representative Methods`.
- Boundary case content folds into `## Related Families`.

### Length
1000–1800 words (unchanged).

---

## Section 4 — Method chapter headings re-anchored to Book_style

### Problem
`method-chapter-writing` SKILL uses `## Example` and `## Software` where `Book_style.md` prescribes `## Worked Example` and `## Practical Guidance`.

### Change
Rename two sections:
- `## Example` → `## Worked Example`
- `## Software` → `## Practical Guidance`

The `## Practical Guidance` section's contract becomes:
- Lead with **when to use / when not to use** prose (Book_style intent).
- Artifacts (libraries, models, codebases) follow as a sub-bullet list. The "every artifact must appear in `pack.structured`" rule is preserved.

### Order (enforced)
Summary, Motivation, Intuition, Theory, Algorithm, **Worked Example**, Interpretation, Strengths, Limitations, **Practical Guidance**, Related Methods.

Verbatim equation/pseudocode rules unchanged.

---

## Section 5 — Verification as a hard gate

### Problem
Stage 18 currently writes `SUMMARY.md` regardless of per-chapter verification status (stages 15/16 only record status; nothing blocks on it). The voice-LM book ships chapters with `status: excluded_gaps_missing` and `status: excluded_unsupported_claims` linked from the front page. Readers can't tell verified content from unverified.

### Change
Stage 18 (manifest + SUMMARY) gains a precondition check:

> If any chapter file's front-matter `status` starts with `excluded_`, abort with a structured error listing offending chapter IDs and reasons. Do NOT write `SUMMARY.md` or `sidebar.json`.

### Iteration loop
A new orchestrator sub-flag `phase=write,fix_excluded=true` is added. When set:

1. Read the list of excluded chapters from `15_verification/`.
2. For each, classify the failure reason:
   - `gaps_missing` → re-dispatch stage 13 (pack rebuild) for that ID, then stage 14 (rewrite) for that ID.
   - `claims_unsupported` → re-dispatch stage 14 only with a directive to drop or re-cite the offending claims.
3. Re-run stage 15 verification on the affected chapters.
4. If any chapter still fails after one retry, fail hard with a final exclusion list.

### Logging
`run_log.csv` records each fix attempt as a row: `stage, chapter_id, attempt, outcome`.

---

## Section 6 — Bibliography bug + thin section beef-up

### Bug 6a: `<title unknown>` in bibliography
**Symptom:** `04_method_taxonomy.md` emits `[arxiv:2502.17239] <title unknown> (<year unknown>)` for every cited paper.

**Cause:** `book-section-writing` is reading from a stale or empty title cache rather than the authoritative source.

**Fix:** Title resolution must read `02_paper_pool/paper_pool.json` (which already carries title and year for every paper). If a cited `arxiv_id` is missing from the pool, fail loudly with the missing IDs rather than emitting `<title unknown>`.

### Beef-up 6b: Goals chapter
**Symptom:** `03_goals.md` is 28 lines; Book_style asks for goal categories with tradeoffs and method-family mapping.

**Fix:** `book-section-writing` for `goals` adds these hard rules:
- ≥ 4 goal categories.
- Each category includes: (a) why it matters, (b) which families help, (c) one tradeoff.
- Min 600 words.

### Beef-up 6c: Appendices
**Symptom:** `99_appendices.md` is a 37-line stub.

**Fix:** Replace single-file output with `99_appendices/` directory. Required files:
- `glossary.md` — auto-built from `06_expansion/known_concepts_snapshot.json`.
- `notation.md` — collected from method packs' `equations[].symbols` if present.
- `datasets.md` — collected from each method pack's evaluation section.
- `software.md` — collected from each method's Practical Guidance artifacts.

Stage 17 (`learning suggestions`) already aggregates most of this; wire its outputs into appendices instead of dropping them.

---

## Section 7 — Migrate single-shot stages to Codex SDK sessions

### Motivation
Five pipeline stages take a small JSON input and produce a small JSON output with no file I/O and no react loop. Dispatching them as full sub-agents loads their instructions, tool stack, and model config into the orchestrator's working context for no behavioral benefit. Routing them through `AsyncCodex.thread_start().run()` puts each invocation behind a single function call.

### Selection rule
> A stage is migration-eligible iff its input fits in a small JSON payload (≲ a few KB) AND its output is a single JSON blob AND it makes no MCP/tool calls.

This rule is deliberately conservative. Tool-using stages (file reads, MCP search) stay as sub-agents because giving the SDK session tool access re-creates the agent.

### Migrations

| Stage | Agent | Action |
|---|---|---|
| 1   | `query_planner`              | → SDK session |
| 5   | `knowledge_gap_detector`     | → SDK session |
| 7   | `paper_ranker`               | → SDK session |
| 12  | `outline_planner`            | → SDK session |
| 16  | `chapter_manifest_builder`   | → SDK session |

The remaining 12 agents stay as sub-agents.

### Code changes — `sdk/codex.py`

Promote the demo file into a small library:

```python
# Existing
def resolve_codex_bin() -> str: ...
def build_config() -> AppServerConfig: ...

# NEW
async def run_one_shot(
    prompt: str,
    *,
    model: str,
    system: str,
    schema: dict | None = None,
    timeout: float = 120.0,
    max_parse_retries: int = 1,
) -> dict | str:
    """One input → one output. Validates against schema; retries once on parse failure."""

async def run_one_shot_batch(
    items: list[dict],
    *,
    model: str,
    system: str,
    schema: dict | None = None,
    concurrency: int = 4,
    timeout: float = 120.0,
) -> list[dict | str]:
    """Parallel one-shots. Replaces sharded sub-agent dispatch for migrated stages."""
```

`run_one_shot` raises on:
- Timeout.
- Schema validation failure after retry.
- Codex transport error.

### Prompt relocation
Move the `instructions` body of each migrated `.toml` into `swarn_research_mcp/config/sdk_prompts/{stage_name}.md`. The `.toml` files for the five migrated agents are **deleted** — retaining them invites drift.

### Orchestrator changes
The orchestrator SKILL gains a small dispatch table:

```yaml
sdk_stages:
  1:
    prompt: sdk_prompts/query_planner.md
    model: gpt-5.4-mini
    schema: schemas/search_plan.json
  5:
    prompt: sdk_prompts/knowledge_gap_detector.md
    ...
```

Stages 1, 5, 7, 12, 16 are documented as "in-process SDK call, no sub-agent dispatch." Sharded parallel logic for stage 7 (ranking many papers) uses `run_one_shot_batch`.

### Codex sub-agent model-bug interaction
The orchestrator currently runs a two-pass `phase=draft|write` workaround for `openai/codex#16548` (sub-agents inherit parent model). The first migration (`query_planner`, cheapest) is the test: if `AsyncCodex.thread_start(model=...)` honors the model arg, the migrated stages no longer need to live inside the `phase=draft` window. Document the result. If threads share the bug, the migration still delivers context relief but no cost relief.

### Risks
- **One-way pain on misclassification.** If a "simple" stage later needs tool access, it must be rebuilt as a sub-agent. Mitigation: start with the five clearest cases, learn before expanding.
- **Schema-constrained output may fail to parse.** `run_one_shot` retries once, then raises. Acceptable.
- **State writes move into orchestrator.** Migrated stages return JSON; orchestrator writes the file. Net context cost is a few KB per stage — acceptable, far smaller than the sub-agent's instruction surface.

### Out of scope for this section
- Stages 2, 8, 9, 10, 11, 13, 14, 15 (writers, extractors, indexers) — they read files; they stay as sub-agents.
- Stage 3 (`weak_graph_extractor`) is borderline (depends on evidence batch size). Defer; revisit after Section 7 lands.

---

## Sequencing

Sections 1–6 are independent of Section 7. They land first because they're tied to a single re-run for validation. Section 7 lands separately so we don't conflate "did we break Book_style alignment" with "did we break SDK dispatch."

| Wave | Sections | Validation |
|---|---|---|
| 1   | §1, §2 (taxonomy)                             | Outline JSON has parts + zero singletons. |
| 2   | §6a (bibliography bug)                        | Cited papers render with title and year. |
| 3   | §3, §4 (heading re-anchor)                    | Generated chapters use Book_style headings exactly. |
| 4   | §6b, §6c (Goals + Appendices)                 | Goals ≥ 600 words; appendices/ directory has 4 files. |
| 5   | §5 (verification gate)                        | A run with a deliberately broken chapter fails stage 18. |
| 6   | §7 (SDK migration)                            | Five stages run via `run_one_shot`; orchestrator log shows no sub-agent dispatch for them. |

Each wave runs end-to-end on a small topic before the next wave starts.

---

## Acceptance criteria

A new run on a small topic must produce:

1. `outline.json` has `parts` array; every family appears in exactly one part; no family has fewer than 2 methods.
2. Every family chapter file has the 10 Book_style `##` headings in order; `## Main Variants` contains a comparison table.
3. Every method chapter has 11 sections including `## Worked Example` and `## Practical Guidance`.
4. `04_method_taxonomy.md` cites every paper with resolvable title and year (no `<title unknown>`).
5. `03_goals.md` is ≥ 600 words and lists ≥ 4 goal categories.
6. `99_appendices/` is a directory with `glossary.md`, `notation.md`, `datasets.md`, `software.md`.
7. Any chapter with `status: excluded_*` blocks `SUMMARY.md` until fixed.
8. Stages 1, 5, 7, 12, 16 dispatch via `run_one_shot` / `run_one_shot_batch`; their `.toml` files are deleted.

---

## What this design does not address

- The two-pass `phase=draft|write` model-bug workaround. Section 7 may incidentally retire it for the migrated stages; the rest stays.
- Cross-run reproducibility of community clustering (deterministic seeds).
- A reader-facing CSS / Hugo / mdBook layer on top of `SUMMARY.md`.
- Multi-language output.

These are real but separate concerns.
