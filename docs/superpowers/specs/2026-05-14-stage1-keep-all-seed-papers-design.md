# Stage 1 Keep-All Seed Papers Design

## Context

The auto-research pipeline currently has two selection layers before Stage 2:

1. `bulk_normal_start_search` gathers papers, applies search-tool relevance gates, and writes the kept raw seed pool to `01_seed_pool/seed_pool_raw.json` plus `bulk_search_results_<timestamp>.json`.
2. The Stage 1 shard builds `02_paper_pool/paper_pool.json` from that raw seed pool. When the raw kept count exceeds `target_seed_papers`, the shard is instructed to downselect to a stratified candidate pool.

That second layer can drop important flagship papers before Stage 2 ever sees them. Stage 2 only processes `02_paper_pool/paper_pool.json`, so any paper omitted there cannot be recovered by weak evidence, graphing, scoring, promotion, or chapter generation.

## Goal

Remove the Stage 1 `seed_pool_raw -> paper_pool.json` downselect. Every paper kept by `bulk_normal_start_search` must be copied into `02_paper_pool/paper_pool.json` and `paper_pool.csv`.

This change does not remove the relevance gates inside `bulk_normal_start_search`; it only removes the later paper-count cap and stratified selection step.

## Non-Goals

- Do not remove positive-keyword, negative-keyword, age, or Codex relevance filtering inside `bulk_normal_start_search`.
- Do not change Stage 2 sharding behavior except that it may receive more papers.
- Do not add manual flagship-paper injection in this change.
- Do not alter existing run artifacts in `research_runs/`.

## Pipeline Contract

Stage 1 will become:

```text
search_plan.json
  -> bulk_normal_start_search(...)
  -> 01_seed_pool/seed_pool_raw.json
  -> 02_paper_pool/paper_pool.json with every seed_pool_raw paper
  -> 02_paper_pool/paper_pool.csv with every seed_pool_raw paper
  -> candidate_pool_report.json describing keep-all behavior
```

If `seed_pool_raw["papers"]` contains `N` papers, then:

- `paper_pool.json` must contain exactly those `N` arXiv IDs.
- `paper_pool.csv` must contain exactly those `N` arXiv IDs.
- `candidate_pool_report.json.selected_total` must equal `N`.
- `candidate_pool_report.json.raw_kept` must equal `N`.

The report should include:

```json
{
  "raw_kept": 391,
  "selected_total": 391,
  "selection_policy": "keep_all_bulk_search_results",
  "per_aspect_selected": {}
}
```

`per_aspect_selected` remains present for compatibility but is no longer used as a selection-quality gate.

## Code Changes

### Runner Prompt

Update `scripts/run_auto_research.py` Stage 1 prompt:

- Replace "Build a stratified 02_paper_pool/paper_pool.json and paper_pool.csv."
- With "Build 02_paper_pool/paper_pool.json and paper_pool.csv from every paper in seed_pool_raw['papers']; do not downselect."

Update the candidate report prompt to require `selection_policy="keep_all_bulk_search_results"` and `selected_total == raw_kept`.

### Bootstrap Validation

Update `validate_bootstrap_stage_0_10_contract()`:

- Remove `target_seed_papers = _bootstrap_target_seed_papers(search_plan)`.
- Remove `required_pool_count = min(target_seed_papers, raw_kept_count)`.
- Require `len(paper_ids) == raw_kept_count`.
- Require the `paper_pool.json` ID set to equal the `seed_pool_raw["papers"]` ID set.
- Keep the minimum pool-size guard when `raw_kept_count >= MIN_BOOTSTRAP_PAPER_POOL`.
- Keep `candidate_pool_report.raw_kept == raw_kept_count`.
- Keep `candidate_pool_report.selected_total == len(paper_ids)`.
- Remove the `candidate_pool_report.target_seed_papers` equality requirement.
- Remove the aspect-coverage validation based on `per_aspect_selected`.

This makes validation fail closed if Stage 1 silently truncates the raw kept pool.

### Search Plan and Agent Instructions

Update these files so new runs no longer ask for `target_seed_papers=200`:

- `.codex/agents/query_planner.toml`
- `.agents/skills/query-planning/SKILL.md`
- `.agents/skills/auto-research-orchestrator/SKILL.md`
- `.codex/config.toml` comments
- `README.md` if it mentions the old cap behavior

Old `search_plan.json` files may still contain `target_seed_papers`; the runner should tolerate that field but ignore it for Stage 1 selection.

## Tests

Update Stage 1 and bootstrap-contract tests in `tests/test_auto_research_runner_cli.py`.

Required coverage:

1. A valid Stage 1 fixture with `raw_kept=40` and `paper_pool=40` still passes.
2. A new regression fixture with `raw_kept=60`, old `target_seed_papers=40`, and `paper_pool=60` passes.
3. A fixture with `raw_kept=60` and `paper_pool=40` fails because Stage 1 truncated kept papers.
4. `candidate_pool_report.target_seed_papers` is no longer required.
5. `candidate_pool_report.selection_policy` is accepted and checked when present.

Run focused tests:

```bash
PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py
```

If runtime is acceptable, also run:

```bash
PYTHONPATH=. pytest
```

## Expected Impact

Stage 2 and later stages may process more papers. This is intentional: Stage 1 should not be the place where potentially important papers are dropped. Later stages already have more evidence for quality decisions:

- Stage 2 creates weak evidence for every paper.
- Stage 7 scores every `paper_pool` paper exactly once.
- Stage 7 promotion still uses `min_promote_score`.
- Stage 8+ only fetches and deeply processes promoted papers.

The cost moves from Stage 1 truncation to evidence-backed scoring, which is the desired behavior.

## Success Criteria

- No code path or skill instruction asks Stage 1 to downselect to `target_seed_papers`.
- New Stage 1 runs copy all `seed_pool_raw["papers"]` into `02_paper_pool/paper_pool.json`.
- Bootstrap validation rejects any run where `paper_pool.json` omits raw kept papers.
- Existing tests pass after being updated for the keep-all contract.
- Existing run artifacts remain untouched.
