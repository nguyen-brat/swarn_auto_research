# run_auto_research.py refactor — design

**Date:** 2026-05-17
**Scope:** `scripts/run_auto_research.py` (3882 lines) → split into a clean `scripts/auto_research_runner/` package + targeted shrinkage. Core logic unchanged.

## Goals

1. Make the runner navigable. The single 3882-line file conflates 13 distinct concerns.
2. Remove genuine dead/wrapper code surfaced by the split.
3. Collapse verbose validators where the message shape is uniform.
4. Keep every behavior — including error message strings asserted by tests — identical.

Out of scope: async/error-handling consistency cleanup, refactoring `swarn_research_mcp/`, refactoring `scripts/auto_research_runner/stage_fulltext.py`'s algorithm.

## Module layout

New modules under `scripts/auto_research_runner/`. Strict left-to-right import order — each module only references earlier ones.

| Order | Module | Owns | ~LOC |
|---|---|---|---|
| 1 | `config.py` | `REPO_ROOT`, `RUNS_ROOT`, executor/timeout/worker defaults, `STAGE_1_*` / `STAGE_7_*` limits, `PRIMARY_ARTIFACTS`, `DIRECT_SHARD_RULES`, `METHOD_PACK_*`, `ARXIV2MD_*`, `NON_BLOCKING_FORM_ISSUE_CHECKS` | 70 |
| 2 | `io_utils.py` | `_load_json`, `_write_json`, `_load_csv_rows`, `_safe_component`, `_safe_relative_path`, `_sha256_file`, `_path_is_relative_to`, `chunked` | 90 |
| 3 | `state.py` *(exists)* | `now_iso`, `ensure_run_control`, `load_run_state`, `save_run_state`, `append_run_log` | 60 |
| 4 | `shared_types.py` *(exists)* | `ShardSpec`, `ShardAttemptResult`, `Stage8MarkdownUnavailable` | 27 |
| 5 | `structured_json.py` *(exists)* | `loads_structured_json`, `load_structured_json_file` | 77 |
| 6 | `artifacts.py` **(new — split from stage_fulltext)** | Read-only predicates and parsers: `_markdown_is_usable`, `_pageindex_artifacts_valid`, `_verified_evidence_is_valid`, `_verified_evidence_claims`, `_claim_grounding_matches_pageindex`, `_flat_pageindex_nodes`, `_tree_pageindex_nodes`, `_stage_8_unavailable_ids`, `_record_stage_8_unavailable_markdown`, `_clear_stage_8_unavailable_markdown`, `_stage_10_quarantine_path`, `_stage_10_quarantined_ids`, `_record_stage_10_quarantine`, `_clear_stage_10_quarantine`, `_verified_evidence_source_keys`, `verified_graph_fragment_filename`, `verified_graph_fragment_relpath`, `_stable_stage_8_shard_id`, `_stable_stage_11_shard_id`, `PAGEINDEX_HEADING_RE`, `_mechanical_summary`, `_pageindex_node_for_tree`, `_build_pageindex`, `_build_pageindex_for_paper`, `_edge_key`, `_source_grounding_key`, `_load_weak_edge_count`, `merge_verified_graph_fragments`, `run_stage_11_merge` | 280 |
| 7 | `paper_pool.py` | `_paper_pool_ids`, `load_paper_pool_arxiv_ids`, `load_paper_pool_records`, `write_paper_pool_records`, `_promoted_ids`, `_promoted_ids_readonly`, `load_promoted_arxiv_ids`, `read_promoted_arxiv_ids`, `load_fulltext_available_promoted_arxiv_ids`, `load_pageindexed_promoted_arxiv_ids`, `load_verified_promoted_arxiv_ids`, `_kept_paper_ids`, `_duplicate_ids`, `_seed_pool_kept_count`, `_seed_pool_ids`, `_paper_pool_records` | 150 |
| 8 | `validation.py` | `primary_artifact_exists`, `STAGE_7_SCORE_COLUMNS`, `_float_score`, `validate_stage_1_search_plan`, `validate_stage_1_keep_all_contract`, `validate_stage_5_outputs`, `validate_stage_6_outputs`, `validate_stage_7_outputs`, `validate_outline_contract`, `validate_verified_global_graph`, `validate_weak_global_graph`, `validate_bootstrap_stage_0_10_contract`, `normalize_stage_7_candidate_csv`, `normalize_stage_7_promoted_json` | 240 |
| 9 | `prompts.py` | `_generic_agent_prompt`, `_stage_11_prompt`, `_typed_target_ref` | 50 |
| 10 | `shards.py` | `_validate_shard_spec`, `_expected_output_exists`, `expected_outputs_exist`, `_shard_dir`, `_write_shard_manifest`, `_append_sdk_thread_index`, `_next_shard_attempt`, `_codex_exec_command`, `_run_cli_shard_attempt`, `_run_sdk_shard_attempt`, `_run_sdk_prompt`, `_sdk_notification_timeout_seconds`, `_run_shard_attempt`, `_run_single_shard`, `run_shards`, `_stage_max_workers_env_name`, `_effective_max_workers`, `run_deterministic_command` | 290 |
| 11 | `stage_fulltext.py` *(slimmed — DI dropped)* | `run_stage_8_impl`, `run_stage_9_impl`, `run_stage_10_impl`, `run_stage_11_impl`. Direct imports of `artifacts`, `paper_pool`, `shards`, `prompts`, `io_utils.chunked`, `state.append_run_log` | 280 |
| 12 | `pack_sources.py` **(new — split from packs)** | `_read_json_or_empty`, `_page_nodes`, `_source_text_from_node`, `_pack_source_node`, `_claim_nodes`, `_structured_nodes`, `_first_available_nodes`, `_section_nodes`, `_outline_method_maps`, `METHOD_PACK_SECTION_TITLES`, `METHOD_PACK_REQUIRED_SOURCE_SECTIONS`, `_normalized_pack_section_title`, `_gap_concept_text`, `_knowledge_gap_candidates`, `_concept_match_spans`, `_concept_matches_evidence`, `_evidence_text_values`, `_method_gap_scope`, `_first_text` | 260 |
| 13 | `packs.py` | `_build_method_pack`, `_build_family_pack`, `_build_book_pack`, `_method_pack_has_required_source_text`, `_method_pack_payload_has_required_source_text`, `build_deterministic_stage_13_packs` | 150 |
| 14 | `chapters.py` | `load_outline`, `build_chapter_targets`, `_validate_chapter_target`, `_expected_chapter_pack`, `_expected_chapter_file`, `_expected_verification_file`, `_chapter_writer_specs`, `_verification_specs`, `_targets_with_blocking_form_issues`, `_write_verification_summary`, `_manifest_chapter_type`, `_outline_entry_for_target`, `_split_markdown_front_matter`, `_strip_references_section`, `_markdown_word_count`, `_yaml_value`, `_write_chapter_front_matter_and_references`, `_verification_passed`, `_verification_status`, `_is_non_blocking_form_issue`, `_blocking_form_issues`, `_has_only_non_blocking_form_issues`, `_load_verification_or_none`, `_references_for_target`, `_build_deterministic_chapter_manifest` | 270 |
| 15 | `stage_5_meta.py` | `STAGE_5_SCHEMA_VERSION`, `_stage_5_paths`, `_stage_5_digest_concepts`, `_stage_5_report_items`, `write_stage_5_metadata`, `stage_5_outputs_valid`, `_stage_17_learning_suggestions` | 120 |
| 16 | `stage_1_search.py` | `_dedupe_str_list`, `_build_stage_1_search_inputs`, `_materialize_stage_1_seed_pool` | 100 |
| 17 | `process_cleanup.py` | `_read_proc_cmdline`, `_proc_cwd_is_under_repo`, `_find_research_mcp_pids`, `cleanup_orphaned_research_mcp_processes`, `cleanup_stage_6_research_mcp_processes` | 70 |
| 18 | `stages.py` | `slugify_topic`, `start_new_run`, `bootstrap_new_run` (kept as retired-stub), `run_stage_1` … `run_stage_18` (no DI wrappers — direct calls), `run_stage_5_aggregate`, `merge_weak_graph_fragments`, `merge_expansion_shards`, `merge_accepted_expansion_into_paper_pool`, `load_expansion_gap_items`, `backfill_expanded_paper_artifacts`, `_fetch_arxiv_markdown_sync` | 700 |
| 19 | `cli.py` | `parse_args`, `_run_stage_handler`, `_validate_stage_1_before_later_start`, `_latest_shard_manifest`, `format_run_status`, `_record_run_failure`, `main` | 150 |

`scripts/run_auto_research.py` becomes a 4-line shim:

```python
from scripts.auto_research_runner.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
```

## Code removed in Commit B (shrink)

- `run_stage_16_legacy_sharded` (line 2824) + `_merge_chapter_manifest_shards` (line 2860) — zero callers in `main()`, zero tests reference them.
- The dependency-injection wrappers `run_stage_8`, `run_stage_9`, `run_stage_10`, `run_stage_11` in the main file. After the artifacts/stage_fulltext split, `stage_fulltext.run_stage_*_impl` imports peers directly. Net ~150 lines.
- Commented dead-code block at the top of `tools/paper_search.py` lines 405-413 (`# ############################## dump code to test only`) — separate cleanup commit.

## Code retained that looked dead

- `bootstrap_new_run` — `test_bootstrap_new_run_is_retired` asserts it raises with "retired". Lives in `stages.py`.
- `_promoted_ids_readonly` legacy-list branch — used by `read_promoted_arxiv_ids` against `promoted_papers.json` that may still be a list during normalization. Stays.

## Shrinkage applied in Commit B

- `validate_stage_1_keep_all_contract` (~100 lines): introduce `_require(cond, msg)` for the ~15 uniform `if X: raise RuntimeError(msg)` blocks. Keeps every error message verbatim. ~25 line save.
- `validate_stage_7_outputs`: same pattern, ~10 line save.
- `validate_stage_5_outputs`: same pattern, ~10 line save.
- `_chapter_writer_specs` + `_verification_specs`: extract shared `_chunked_specs(stage, agent, model, target_type_key, run_dir, chunks, payload_fn, expected_fn)`. ~30 line save.
- `run_stage_13` (lines 2424-2441): fix the broken indentation inside the comprehension.
- `normalize_stage_7_promoted_json`: tighten with comprehensions, ~10 line save.

Expected final size: ~2600 LOC across 19 modules vs current 3882 in one file (~33% net reduction once `run_stage_16_legacy_sharded`, DI wrappers, and verbose validators are collapsed).

## Migration sequence

### Commit A — move only

1. Snapshot current test status: `uv run pytest tests/` and record pass/fail.
2. Create modules 1, 2, 6, 7–19 (preserving exact function bodies; only changes are `from .X import Y` lines).
3. Update `scripts/run_auto_research.py` to the 4-line shim. **No re-exports** — symbols live where they're defined.
4. Update test imports — touch 5 files:
   - `tests/test_auto_research_runner_state.py` — `append_run_log`, `ensure_run_control`, `load_run_state`, `save_run_state` (already importable from `state`); `primary_artifact_exists` ← `validation`; `main` ← `cli`.
   - `tests/test_auto_research_runner_dispatch.py` — `ShardSpec` ← `shared_types`; `_codex_exec_command`, `expected_outputs_exist`, `run_shards` ← `shards`.
   - `tests/test_auto_research_runner_stage11.py` — `merge_verified_graph_fragments`, `run_stage_11_merge` ← `artifacts`; `run_stage_11` ← `stages`.
   - `tests/test_auto_research_runner_cli.py` — split across `shared_types`, `chapters`, `cli`, `stages`, `shards`, `state`, `validation`. ~30 distinct imports.
   - `tests/test_stage_5_pipeline.py` — `run_stage_5`, `run_stage_17` ← `stages`.
5. Update all `patch("scripts.run_auto_research.X")` strings (40 total) to call-site modules:
   - `patch("scripts.run_auto_research.run_shards")` → `patch("scripts.auto_research_runner.stages.run_shards")` everywhere it's called from a stage runner.
   - `patch("scripts.run_auto_research._run_single_shard")` → `patch("scripts.auto_research_runner.shards._run_single_shard")`.
   - `patch("scripts.run_auto_research._run_sdk_shard_attempt")` → `patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt")`.
   - `patch("scripts.run_auto_research.run_deterministic_command")` → `patch("scripts.auto_research_runner.stages.run_deterministic_command")` (since stages call it).
6. Run `uv run pytest tests/`. Must match baseline. Commit.

### Commit B — shrink

1. Drop `run_stage_16_legacy_sharded` and `_merge_chapter_manifest_shards`.
2. Drop DI wrappers `run_stage_8/9/10/11`; rewrite `stage_fulltext.run_stage_*_impl` signatures to take only `run_dir`, `max_workers`, `executor`, importing peers directly.
3. Introduce `_require` and collapse the uniform validator blocks (preserving every error message string verbatim).
4. Extract `_chunked_specs` shared by `_chapter_writer_specs` / `_verification_specs`.
5. Tighten `normalize_stage_7_promoted_json`.
6. Fix `run_stage_13` indentation.
7. Run `uv run pytest tests/`. Must match baseline. Commit.

## Risks and mitigations

- **Patch-target rewrite blast radius (40 sites).** Mitigation: each new target is enumerated above; do as one mechanical sed-like sweep + grep verification.
- **Hidden circular imports.** Mitigation: strict left-to-right order in the table above; CI runs `python -c "import scripts.auto_research_runner.cli"` to surface cycles at import time.
- **Tests asserting exact error message substrings.** Mitigation: validator collapses keep messages verbatim; `_require` takes the message as-is.
- **`_stage_11_prompt` placement** (flagged by reviewer round 2). Locked into `prompts.py` adjacent to `_generic_agent_prompt`.

## Acceptance criteria

- `uv run pytest tests/` passes with the same set of tests as before Commit A.
- `scripts/run_auto_research.py` ≤ 10 lines.
- No module exceeds 800 lines.
- Import order acyclic; verified by `python -c "import scripts.auto_research_runner.cli"`.
- `grep -rn 'scripts.run_auto_research' tests/` returns zero hits except the 4-line shim's docstring (if any).
