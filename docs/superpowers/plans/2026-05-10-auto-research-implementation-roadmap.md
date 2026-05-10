# Auto Research Implementation Roadmap

> **For agentic workers:** Start here. Do not implement from the long reviewed source plan directly. Load only this roadmap and the single shard assigned to you.

**Goal:** Implement the auto-research handbook upgrade without losing requirements to context limits.

**Architecture:** The reviewed book-style plan is split into five smaller shard plans with explicit prerequisites and exit criteria. The SDK pilot remains independent and can run before or after the book shards.

**Tech Stack:** Python 3.11, pytest, Markdown skill contracts, Codex agent configuration.

---

## Global Invariants

These apply to every shard. Do not weaken them while implementing a later shard.

- Stage 12.5 normalizes `12_taxonomy/outline.json` before Stage 13 builds chapter packs.
- Stage 18 calls `assert_no_singletons(outline)` and refuses raw singleton families.
- `standalone` is the only allowed singleton group; do not create `other_*` catch-all families.
- `standalone` / `is_group` families have no family chapter file and render methods flat under `standalone_methods`.
- `BOOK_FILE_BY_ID["appendices"] == "appendices"`; appendices is a directory, not `99_appendices.md`.
- Missing citation metadata must not block a readable book. It writes an unresolved marker in `references.md` and a `citation/<arxiv_id>` item in `NEEDS_REVIEW.md`.
- Excluded chapters are quarantined: they remain on disk, are omitted from main navigation, and are listed in `16_book/NEEDS_REVIEW.md`.
- Every shard must keep tests focused and run the shard's targeted tests before committing.

## Source Plans

- Reviewed source: `docs/superpowers/plans/2026-05-10-codex-book-style-alignment.md`
- SDK pilot: `docs/superpowers/plans/2026-05-10-codex-sdk-context-relief-pilot.md`

The reviewed source plan is retained for audit and reference. Implementation agents should use the shard plans below.

## Execution Order

1. `docs/superpowers/plans/2026-05-10-auto-research-00-fixture-and-citation-foundation.md`
2. `docs/superpowers/plans/2026-05-10-auto-research-01-taxonomy-parts-singletons.md`
3. `docs/superpowers/plans/2026-05-10-auto-research-02-heading-and-chapter-style.md`
4. `docs/superpowers/plans/2026-05-10-auto-research-03-appendices-and-navigation.md`
5. `docs/superpowers/plans/2026-05-10-auto-research-04-quarantine-and-final-validation.md`

The SDK pilot plan is independent:

- `docs/superpowers/plans/2026-05-10-codex-sdk-context-relief-pilot.md`

Run the SDK pilot first if you want to validate `run_one_shot`; otherwise it can wait until after the book shards.

## Reliability Follow-Up

Before running more long end-to-end pilots, implement:

- `docs/superpowers/plans/2026-05-10-auto-research-durable-runner.md`

This runner fixes the observed failure mode where an interactive parent session stops after one shard returns while later shard notifications arrive after task completion.

## Agent Strategy

Use sequential subagent-driven development. Do not run implementation agents in parallel across shards because the shards repeatedly touch `swarn_research_mcp/research_book.py`, `tests/`, and `.agents/skills/`.

For each task inside a shard:

1. Dispatch one fresh implementer with only the roadmap, the current shard, and any files named by that task.
2. Run the task's targeted tests.
3. Run a spec-compliance review against the shard text.
4. Run a code-quality review focused on regressions and integration risks.
5. Commit the task before moving to the next task.

At each shard boundary, run the shard exit criteria and inspect `git status --short` before proceeding.

## Stop Gates

Stop and ask the user before continuing if any of these happen:

- A shard requires changing the architecture from the reviewed source plan.
- A targeted test cannot be made to pass without weakening a global invariant.
- The implementation agent wants to merge or delete existing `.codex/agents/*.toml` outside the SDK pilot's explicit scope.
- The audited run validation exposes a new class of issue not represented in the current shard.

## Final Handoff

After Shard 04 completes, run:

```bash
pytest tests/ -v
```

Then run the audited-run commands in Shard 04 Task F.1. Only after those checks should a final reviewer inspect the full branch.
