---
name: auto-research-orchestrator
description: Run the auto-research pipeline end-to-end for one topic — Book_style.md output across three chapter tiers.
---

# Auto Research Orchestrator

## Preferred durable runner

For end-to-end runs, prefer:

```bash
python scripts/run_auto_research.py --topic "<topic>" --phase draft
python scripts/run_auto_research.py --run-id <run_id> --phase write --resume
```

The Python runner owns durable stage state, shard manifests, artifact checks, retries, and deterministic merges. This skill remains the behavioral contract for every stage, but an interactive parent Codex session should not be the long-running control plane for full end-to-end runs.

## Inputs
- `topic` (required for `phase=draft|all`)
- `phase` ∈ {`draft`, `write`, `all`}, default `all`
- `run_id` (required when `phase=write`)
- `knowledge_base_path` (default `.agents/knowledge_base.md`)
- normal/survey queries, positive/negative keywords (optional; derive from topic)

## Two-pass execution (Codex sub-agent model bug workaround)

Codex bug [openai/codex#16548] makes every sub-agent run as the parent session's model regardless of its `.toml`. Run two passes so cheap stages use mini and writing uses gpt-5.4:

| Phase   | Stages | Recommended parent |
|---------|--------|--------------------|
| `draft` | 0–13   | `gpt-5.4-mini`     |
| `write` | 14–17  | `gpt-5.4`          |
| `all`   | 0–17   | (whatever)         |

Operator workflow:
1. `codex --model gpt-5.4-mini` → orchestrator with `phase=draft` + topic. Runs 0–13. Status line prints the `run_id`.
2. `codex --model gpt-5.4` → orchestrator with `phase=write` + `run_id`. Runs 14–17.

End-of-phase status (print verbatim):
- draft: `draft phase complete. run_id={run_id}. Now relaunch codex with --model gpt-5.4 and ask the orchestrator with phase=write run_id={run_id}.`
- write: `write phase complete. run_id={run_id}. Chapters at research_runs/{run_id}/14_chapters/.`

## phase=write,fix_excluded=true (single retry)
When the operator re-launches with `phase=write fix_excluded=true`:
1. Read offender list from `15_verification/{type}/{id}_verification.json`.
2. For each offender:
   - `gaps_missing` -> re-dispatch stage 13 (pack rebuild) for that ID, then stage 14.
   - `claims_unsupported` -> re-dispatch stage 14 with a directive to drop or re-cite offending claims.
3. Re-run stage 15 verification on affected chapters.
4. Re-run stage 18 (`generate_book_artifacts`); chapters now passing get added to main navigation, the rest stay quarantined in `NEEDS_REVIEW.md`. No retry budget - a single attempt per offender per invocation.
5. Each fix attempt logs a row in `run_log.csv`: `stage,chapter_id,attempt,outcome`.

## Idempotent resume
Before dispatching any stage, check whether its primary output exists. If yes, log `skipped: artifact present` to `run_log.csv` and continue. Phase boundaries are hard: never cross them. `phase=write` errors out if `12_taxonomy/outline.json` or `13_chapter_packs/{book,families,methods}/` are missing.

| Stage | Primary artifact |
|-------|-----------------|
| 0  | `run_config.json` |
| 1  | `00_input/search_plan.json` and `02_paper_pool/paper_pool.json` |
| 2  | every paper has `04_weak_evidence/{arxiv_id}.json` |
| 3  | `05_weak_graph/weak_global_graph.json` |
| 4  | `06_expansion/known_concepts_snapshot.json` |
| 5  | `06_expansion/knowledge_gap_report.json` + `expansion_need_queue.json` |
| 6  | `06_expansion/expansion_round_01.json` (or queue empty) |
| 7  | `07_scoring/promoted_papers.json` |
| 8  | every promoted paper has `08_full_markdown/{arxiv_id}.md` |
| 9  | every promoted paper has `09_pageindex/trees/{arxiv_id}.tree.json` |
| 10 | every promoted paper has `10_verified_evidence/{arxiv_id}.json` |
| 11 | `11_verified_graph/global_graph.json` |
| 12 | `12_taxonomy/outline.json` (three-tier) |
| 12.5 | `12_taxonomy/outline.json` (normalized — `python -m swarn_research_mcp.research_book {run_dir} --normalize-outline`) |
| 13 | every outline ID has its pack under `13_chapter_packs/{book,families,methods}/` |
| 14 | every outline ID has its file under `14_chapters/{book,families,methods}/` |
| 15 | every chapter has `15_verification/{type}/{id}_verification.json` |
| 16 | every chapter target except `book:appendices` has YAML front matter + `16_book/chapters_manifest.json` lists all dispatched targets |
| 17 | `17_learning_suggestions/knowledge_to_add.md` |
| 18 | `16_book/SUMMARY.md` + `16_book/sidebar.json` + `16_book/appendices/`; validation has no blocking contract issues |

## Stage 18 verification quarantine
At stage 18, `generate_book_artifacts` ALWAYS produces `SUMMARY.md`, `sidebar.json`, `04_method_taxonomy.md`, and `appendices/` (assuming Stage 12.5 normalized the outline). Chapters whose front-matter `status` starts with `excluded_` are **quarantined** - they remain on disk under `14_chapters/` but are NOT linked from main navigation. Missing citation metadata is written as a `citation/<arxiv_id>` NEEDS_REVIEW item while `references.md` keeps an unresolved marker; this is review debt, not a hard book-generation failure. The list of quarantined chapters and citation issues is written to `16_book/NEEDS_REVIEW.md`, which always exists (even if empty).

## Budgets
```
max_seed_papers   = 50    # Stage 1 only
max_expansion_gaps = 5    # gap-topic count, not paper count
max_expansion_rounds = 1
min_gap_importance = 0.70
min_confusion_risk = "medium"
min_promote_score  = 0.45
shard_size_papers  = 5
shard_size_gaps    = 1
shard_size_method_packs = 1   # Stage 13 methods only — pack builder ingests raw markdown
shard_size_chapters = 2       # Stages 13 (book/family), 14, 15, 16 — read slim packs only
verified_sections_per_paper = 20
```

**Cap policy:** Stage 1 caps initial search at `max_seed_papers`. After that, no paper-count caps anywhere. Stage 6 keeps every paper meeting the acceptance rules; Stage 7 promotes every paper with `final_score ≥ min_promote_score`. Quality drops out via the relevance gate, not truncation.

## Sharded parallel execution (any stage marked PARALLEL)
1. Build ordered item list.
2. Split into shards of `shard_size_*` (last shard may be shorter).
3. Dispatch concurrently — each call carries only its slice + a unique `shard_id`.
4. Wait for ALL shards. On failure, re-dispatch only the failing shard ONCE before stopping. Exception: if the failure is `context_length_exceeded`, do NOT re-dispatch the same slice — split it into 1-item shards and dispatch each separately. A 1-item shard that still overflows is logged and skipped (do not stop the stage for it).
5. Per-item outputs live at canonical filenames — shards never collide.
6. Run any required sequential merge after all shards finish.

Cap: ≤ 50 concurrent sub-agents per stage. If a stage has more than 50 shards, dispatch in concurrent waves of 50 — wait for one wave to finish, then launch the next. (Codex `max_threads` in `.codex/config.toml` may be higher to allow cross-stage headroom, but the per-stage ceiling stays at 50.)

## Delegation hard rules
- Do not replace Stages 12–17 with an inline parent-script generator. The parent orchestrator may create folders, merge shard outputs, and run deterministic validators, but taxonomy, packs, chapter prose, verification, and manifest/front-matter edits must come from the configured stage agents.
- If the current session cannot dispatch the configured stage agents, stop the run and write a failure row to `run_log.csv`. Do not infer schemas from old runs and do not create substitute artifacts from parent-authored Python or Markdown templates.
- Do not mark a chapter `passed` from the parent process. `passed` only comes from verifier output after form checks, claim checks, gap checks, and actual word-count checks.
- Do not create synthetic verification JSON with zero claims and zero form issues. If a verifier cannot check a chapter, the stage failed.
- If any method pack lacks source text for theory, algorithm, example, or limitations, retry the pack builder once and then stop. Do not write a method chapter from an empty pack.

## Stages

### 0 — Create run (or resume)
- `phase=write`: load `run_config.json` and verify outline + packs exist; error otherwise. No edits.
- Else: slugify topic → `research_runs/{slug}-{YYYYMMDD-HHMMSS}/`. Create subfolders:
  ```
  00_input  01_seed_pool  02_paper_pool  03_overviews
  04_weak_evidence  05_weak_graph  06_expansion  07_scoring
  08_full_markdown  09_pageindex  10_verified_evidence
  11_verified_graph  12_taxonomy
  13_chapter_packs/{book,families,methods}
  14_chapters/{book,families,methods}
  15_verification/{book,families,methods}
  16_book  17_learning_suggestions
  ```
- Write `run_config.json` (budgets + topic + KB path), `00_input/topic.md`, init `run_log.csv` with header `timestamp,stage,status,detail`.

### 1 — Seed pool

**1a. Plan the search.** Dispatch `query_planner` with the topic and any user-supplied queries/keywords. It writes `00_input/search_plan.json` covering 4–8 distinct aspects of the topic (method families, architectural enablers, training/adaptation, evaluation, foundational priors, boundary aspects). This is the step that prevents missing key papers — narrow plans miss whole sub-areas.

**1b. Execute the search.** Read `search_plan.json`. Build the union across all aspects:
- `queries` = union of every aspect's `normal_queries`
- `survey_queries` = union of every aspect's `survey_queries`
- `positive_keywords` = union of every aspect's `positive_keywords` (a kept paper needs to match at least one)
- `negative_keywords` = union of every aspect's `negative_keywords` ∪ `global_negative_keywords`

Call MCP `bulk_normal_start_search` ONCE with these unioned lists and `output_dir=01_seed_pool/`. The tool dedupes results internally.

**1c. Build the pool.** Save the raw response as `01_seed_pool/seed_pool_raw.json`. Build `02_paper_pool/paper_pool.{json,csv}` from the kept papers, capping at `max_seed_papers`. Stop if the pool has < 10 papers (topic too narrow — re-run query_planner with a broader topic phrasing first).

### 2 — Weak evidence [PARALLEL]
Shard `paper_pool.keys()` → `weak_evidence_extractor` per shard. Success: every paper has `04_weak_evidence/{arxiv_id}.json`.

### 3 — Weak graph [PARALLEL fragments + merge]
Shard same list → `weak_graph_extractor` writing only `05_weak_graph/fragments/{arxiv_id}.json`. Merge: dedupe nodes by id, union edges → `05_weak_graph/weak_global_graph.json`.

### 4 — Read knowledge base
Dispatch `knowledge_base_reader`.

### 5 — Detect gaps
Dispatch `knowledge_gap_detector`. Skip Stage 6 only if `expansion_need_queue.json.items` is empty.

### 6 — Expand pool [PARALLEL per gap]
Shard queue items → `paper_expander` (one gap per shard by default). Each shard writes shard-local round file + accepted/rejected CSVs.

Merge:
- Concatenate per-shard round files into `expansion_round_01.json` (`status=completed` if any shard searched).
- Concatenate CSVs into canonical `accepted_candidates.csv` / `rejected_candidates.csv`.
- No paper-count cap — add every accepted paper to `paper_pool.json`.

Validation: any shard returning `status=skipped` despite non-empty `gap_items` is re-dispatched ONCE. If the retry skips, stop.

After acceptance, re-run Stage 2 for the new arxiv_ids only.

### 7 — Score and promote
Dispatch `paper_ranker` with `min_promote_score`.

### 8 — Full Markdown
Per promoted paper: MCP `get_paper_markdown` → `08_full_markdown/{arxiv_id}.md`. Log each fetch.

### 9 — PageIndex [PARALLEL]
Shard promoted arxiv_ids → `paper_indexer`. Per-paper output, no merge.

### 10 — Verified evidence [PARALLEL]
Shard promoted arxiv_ids → `verified_evidence_extractor`. Validation: every claim has non-empty `source_node_id` + `source_lines`. Zero-claim papers re-dispatched ONCE; still empty → log + drop from chapters (not fatal).

### 11 — Verified graph [PARALLEL fragments + merge]
Shard promoted arxiv_ids → `verified_graph_extractor`. Merge:
- Dedupe nodes, union edges.
- Compare against `weak_global_graph.json`; list weak edges with no verified counterpart.
- Write `11_verified_graph/global_graph.json` + `graph_report.md`.

### 12 — Taxonomy and outline (sequential)
Dispatch `outline_planner` → `12_taxonomy/communities.json`, `taxonomy.json`, `outline.json` (three-tier: 8 book sections + families (no upper cap) + one method per promoted paper). Stop if `outline.methods` is empty.

## Stage 12.5 — Normalize outline (deterministic)
After Stage 12 writes `outline.json` and BEFORE Stage 13 builds packs, run:

  `python -m swarn_research_mcp.research_book research_runs/{run_id} --normalize-outline`

This calls `merge_singletons`, which deterministically merges every single-method family into its nearest non-singleton family when strong graph evidence exists; otherwise the method is placed under the `standalone` group in the `standalone_methods` part. Stage 13's pack-building reads the normalized outline; Stage 18's `generate_book_artifacts` asserts the outline is normalized and refuses to render otherwise.

### 13 — Chapter packs [PARALLEL three-tier]
Build typed `pack_targets` in canonical order: 8 book sections → all families (outline order) → all methods (grouped by family in outline order). Shard → `chapter_pack_builder`. Use `shard_size_chapters` for book + family targets and `shard_size_method_packs` (=1) for method targets — method packs ingest raw paper markdown and overflow when bundled.

Validation: every method pack has non-empty `section_text` on theory/algorithm/example/limitations source nodes (the single biggest determinant of method-chapter depth). Failing pack re-dispatched ONCE.

### Phase boundary — end of `draft`
If `phase=draft`, stop here. Print the draft-complete status line. Never dispatch Stages 14–17.

### 14 — Write chapters [PARALLEL three-tier]
Three writer agents run concurrently, each sharded independently:
- `method_chapter_writer` shards over `outline.methods[].id` → `14_chapters/methods/{id}.md`
- `family_chapter_writer` shards over `outline.families[].id` → `14_chapters/families/{id}.md`
- `book_section_writer` shards over `outline.book_sections[].id` → `14_chapters/book/{NN}_{id}.md`

The three tiers share no artifacts — fully concurrent.

### 15 — Verify chapters [PARALLEL three-tier, with form rewrite]
Build typed `chapter_targets` list (same order as Stage 13) excluding `book:appendices`; appendices are generated deterministically in Stage 18. Shard → `verifier`. Each shard writes per-target verification JSON at `15_verification/{book|families|methods}/{id}_verification.json`.

For any target with `form_issue_count > 0`: re-dispatch the matching writer ONCE with `form_issues` feedback, then re-dispatch `verifier` ONCE — the per-target JSON is overwritten in place. If issues persist, log and continue. Targets with `claims_unsupported > 0` or `gaps_missing > 0` are NOT auto-rewritten — they get marked excluded in the manifest.

**Stage-close (sequential, run by parent, exactly ONCE after all rewrite/reverify dispatches have returned):**
1. Source of truth = per-target `_verification.json` files. Iterate `chapter_targets` in canonical order; load each JSON; emit one CSV row from `summary` + top-level `passed`. Targets with no JSON = stage failure (do not write a partial CSV).
2. Write `verification_summary.csv` atomically (write to `.tmp`, then rename) — never append, never merge from shards.
3. Verifier sub-agents must NOT write `verification_summary.csv` directly, and must NOT write per-shard summary CSVs. The parent owns this file.
4. Stage 15 is closed iff per-target JSON count == `len(chapter_targets)` AND `verification_summary.csv` has exactly that many rows.

### 16 — Chapter manifest [PARALLEL three-tier + merge]
Same typed `chapter_targets`, still excluding `book:appendices`. Appendices are not dispatched to `chapter_manifest_builder`; Stage 18 writes them through `generate_book_artifacts` / `_build_appendices_dir`. Shard → `chapter_manifest_builder`. Each shard:
- Edits chapter file in place: prepend/replace YAML front matter; append/replace `## References`. Prose stays byte-for-byte.
- Writes shard-local `16_book/chapters_manifest_shard_{shard_id}.json`.

Merge: concatenate shards into `16_book/chapters_manifest.json` in canonical order. Delete shard files.

Failed-verification chapters keep their file; front-matter `status` records the reason.

### 17 — Learning suggestions
Read `knowledge_gap_report.json`; list gaps recurring across multiple papers grouped by category. Write `17_learning_suggestions/knowledge_to_add.md`:
```markdown
# Suggested Knowledge Base Additions

Run: {run_id}

## <category>
- <concept> — needed by <N> papers
```
Do NOT modify `.agents/knowledge_base.md`.

### 18 — Deterministic book artifacts and contract validation
Run:
```bash
python -m swarn_research_mcp.research_book research_runs/{run_id} --generate
python -m swarn_research_mcp.research_book research_runs/{run_id} --validate
```

This stage is deterministic and fixes the generated book artifacts that must be complete rather than improvised:
- `14_chapters/book/04_method_taxonomy.md` is regenerated from `12_taxonomy/outline.json` and must link every family and every method.
- `16_book/SUMMARY.md` and `16_book/sidebar.json` are generated as navigation artifacts for a left-sidebar renderer.
- `16_book/appendices/` is generated through `_build_appendices_dir` with `glossary.md`, `notation.md`, `datasets.md`, `software.md`, and `references.md`.

Validation is blocking for structural contract issues:
- every promoted paper has a method entry, unless a future explicit drop list exists;
- no duplicate normalized family titles;
- no empty families;
- no noisy sentence-like family titles;
- no method IDs that look like paper section headings;
- method taxonomy links every family and every method;
- appendices reference every promoted paper, with missing citation metadata recorded as `citation/<arxiv_id>` review debt rather than a hard book-generation failure;
- method packs have non-empty source text for theory, algorithm, example, and limitations;
- every method chapter has at least 1500 words;
- every family chapter has at least 1000 words and includes `## Core design pattern`;
- no method or family chapter is marked `passed` with a below-threshold word count.

Non-passing chapter statuses are reported as warnings by the validator. They should still be reviewed, but they do not block navigation artifact generation unless a structural contract issue is also present. Excluded chapters are quarantined from main navigation and listed in `16_book/NEEDS_REVIEW.md`.

## Failure handling
On any stage failure, append a row to `run_log.csv` and stop. Sub-agent return strings are logged verbatim.

## Success criteria
1. `run_config.json` exists.
2. `paper_pool.json` ≥ 40 papers.
3. Every `04_weak_evidence/*.json` has non-empty `reader_needed_concepts`.
4. `knowledge_gap_report.json` has all three buckets.
5. Every `accepted_candidates.csv` row has `added_for_gap` + `why_needed`.
6. `promoted_papers.json` has ≥ 1 entry, each with `final_score ≥ min_promote_score`. No upper cap.
7. `08_full_markdown/` has one file per promoted paper.
8. `09_pageindex/trees/` has one valid tree per promoted paper.
9. Every `10_verified_evidence/*.json` has claims with `source_node_id` + `source_lines`.
10. `11_verified_graph/global_graph.json` exists; every edge has `confidence='verified'` + `source_node_id`.
11. `outline.json` has 8 `book_sections`, ≥ 1 `families`, one `methods` entry per promoted paper.
12. Every method pack has non-empty `section_text` on theory/algorithm/example/limitations sources; every family pack has ≥ 1 method_id; all 8 book packs exist.
13. Every outline ID has its markdown file in the right `14_chapters/{book|families|methods}/`.
14. Every chapter has its verification file. Every method chapter passes (`claims_unsupported=0, gaps_missing=0, form_issue_count=0, word_count ≥ 1500, equations_rendered ≥ 1` when pack provides equations); every family chapter has `word_count ≥ 1000` and `## Core design pattern`.
15. Every dispatched chapter target has valid YAML front matter (`chapter_id, chapter_type, title, slug, status`) and ends with `## References`. `chapters_manifest.json` lists all three tiers in canonical order except `book:appendices`. No `handbook.md`.
16. `17_learning_suggestions/knowledge_to_add.md` exists.
17. `16_book/SUMMARY.md`, `16_book/sidebar.json`, and `16_book/appendices/{glossary.md,notation.md,datasets.md,software.md,references.md}` exist; `python -m swarn_research_mcp.research_book research_runs/{run_id} --validate` exits 0.
