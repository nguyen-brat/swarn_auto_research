---
name: nguyen-brat
description: Behavioral guidelines to reduce common LLM coding mistakes. Use when writing, reviewing, or refactoring code to avoid overcomplication, make surgical changes, surface assumptions, and define verifiable success criteria.
license: MIT
---

## Auto-research router

When the user asks for **deep research**, a **handbook**, a **literature survey**, a **book/chapter on a topic**, or anything of the form *"research X for me"* / *"do research about X"* / *"build a handbook on X"*, you MUST follow `.agents/skills/deep-research-supervisor/SKILL.md`. The supervisor skill launches the durable SDK runner and uses `.agents/skills/auto-research-orchestrator/SKILL.md` as the stage contract. Do not improvise.

**No parent-script substitutes:** if the current Codex session cannot dispatch the configured agents from `.codex/agents/`, stop and report that the agent runner is unavailable. Never replace the taxonomy, chapter-pack, chapter-writing, verification, or manifest stages with a parent-authored inline Python script or handcrafted Markdown generator.

**Path discipline (HARD RULE for every sub-agent in the auto-research pipeline):** every file the orchestrator and its sub-agents read or write lives under `research_runs/{run_id}/`. Whenever a skill or agent prompt names a path like `14_chapters/methods/foo.md`, that path is **shorthand for** `research_runs/{run_id}/14_chapters/methods/foo.md`. Never write to repo-relative paths or to the current working directory — always prefix with `research_runs/{run_id}/`. The only exceptions are `.agents/`, `.codex/`, and `Book_style.md` which are read-only inputs to the pipeline.

**Default behavior: run end-to-end.** When the user asks for research with no phase keyword, run `phase=all` (Stages 0–17) without asking, without announcements, without confirmation. The user always launches the parent on `gpt-5.4`, so the two-pass workaround is unnecessary.

Inputs to the orchestrator (decide ONLY from observable user input — do not try to detect your own model):
- `topic` = the topic the user gave (use it verbatim; if missing, ask once before starting).
- `phase`:
  1. If the user's message contains `phase=draft` / `phase=write` / `phase=all` → use that exact value.
  2. Else if the user's message contains a `run_id=...` (or "run_id <id>" / "from run <id>") → `phase=write` with that `run_id`.
  3. Else → `phase=all`. Just start. Do NOT ask for confirmation.
- `run_id` = required only for `phase=write`. The user pastes the ID printed at the end of a previous draft.

When the orchestrator finishes a phase, print its end-of-phase status line **verbatim** so the user can copy/paste the next command (only relevant for explicit `phase=draft` runs — the `phase=all` path's status line just points at the chapter directory).

**Cost-saving two-pass workflow (opt-in):** the user may explicitly ask for `phase=draft` first (Stages 0–13 only) when they want to redo Stages 14–17 later under different settings. Only follow this path when the user explicitly types `phase=draft` — never infer it.

For all other tasks (code edits, refactors, debugging, reviews), follow the rules below — never invoke the orchestrator for non-research tasks.

---

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
