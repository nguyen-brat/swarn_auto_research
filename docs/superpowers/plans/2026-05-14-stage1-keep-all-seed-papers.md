# Stage 1 Keep-All Seed Papers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Stage 1 paper-count downselect so every paper kept by `bulk_normal_start_search` is copied into `02_paper_pool/paper_pool.json` before Stage 2.

**Architecture:** Keep `bulk_normal_start_search` relevance filtering unchanged. Change the Stage 1 handoff contract from capped stratified selection to keep-all copying, then make bootstrap validation fail if any raw kept paper is missing from `paper_pool.json`. Update prompts, skills, docs, and tests so no active instruction asks for `target_seed_papers` downselection.

**Tech Stack:** Python 3.11+, pytest, Codex local skills/prompts, JSON/CSV run artifacts.

---

## File Map

- Modify `tests/test_auto_research_runner_cli.py`: update bootstrap fixtures and add regression tests for keep-all paper pools.
- Modify `scripts/run_auto_research.py`: remove Stage 1 target-cap validation, require raw kept IDs and paper pool IDs to match, and update the Stage 1 shard prompt.
- Modify `.codex/agents/query_planner.toml`: stop asking the query planner to emit `target_seed_papers=200`.
- Modify `.agents/skills/query-planning/SKILL.md`: remove `target_seed_papers` from the required schema.
- Modify `.agents/skills/auto-research-orchestrator/SKILL.md`: replace Stage 1 cap policy with keep-all policy.
- Modify `.codex/config.toml`: update budget comments so they do not mention `target_seed_papers`.
- Optionally modify `README.md` only if an active run instruction mentions the old cap.

---

### Task 1: Write Keep-All Bootstrap Tests

**Files:**
- Modify: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Update the Stage 1 dispatch test fixture**

Change `test_run_stage_1_dispatches_query_planner_and_requires_pool_report` so the fake Stage 1 output uses the new report contract and the prompt assertion checks the keep-all instruction.

Replace the `search_plan.json` write in that test with:

```python
(run / "00_input" / "search_plan.json").write_text(
    json.dumps({"topic": "Demo", "aspects": aspects})
)
```

Replace the `candidate_pool_report.json` payload in that test with:

```python
(run / "02_paper_pool" / "candidate_pool_report.json").write_text(
    json.dumps(
        {
            "raw_kept": 40,
            "selected_total": 40,
            "selection_policy": "keep_all_bulk_search_results",
            "per_aspect_selected": {},
        }
    )
)
```

After the existing prompt assertions, add:

```python
assert "from every paper in seed_pool_raw" in calls[0].prompt
assert "Build a stratified" not in calls[0].prompt
```

- [ ] **Step 2: Run the Stage 1 dispatch test and verify it fails**

Run:

```bash
PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_run_stage_1_dispatches_query_planner_and_requires_pool_report -v
```

Expected: FAIL because `run_stage_1` still says `Build a stratified 02_paper_pool/paper_pool.json and paper_pool.csv.`

- [ ] **Step 3: Make the bootstrap fixture configurable**

Change `_write_valid_bootstrap_contract` from:

```python
def _write_valid_bootstrap_contract(run):
    ids = [f"2501.{idx:05d}" for idx in range(200)]
```

To:

```python
def _write_valid_bootstrap_contract(run, ids=None):
    if ids is None:
        ids = [f"2501.{idx:05d}" for idx in range(200)]
```

Replace its `search_plan.json` payload with:

```python
(run / "00_input" / "search_plan.json").write_text(
    json.dumps({"aspects": aspects})
)
```

Replace its `candidate_pool_report.json` payload with:

```python
(run / "02_paper_pool" / "candidate_pool_report.json").write_text(
    json.dumps(
        {
            "raw_kept": len(ids),
            "selected_total": len(ids),
            "selection_policy": "keep_all_bulk_search_results",
            "per_aspect_selected": {},
        }
    )
)
```

- [ ] **Step 4: Add regression test for legacy target ignored**

Add this test after `test_validate_bootstrap_contract_accepts_real_discovery_shape`:

```python
def test_validate_bootstrap_contract_ignores_legacy_target_seed_papers(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(60)]
    _write_valid_bootstrap_contract(run, ids=ids)
    search_plan = json.loads((run / "00_input" / "search_plan.json").read_text())
    search_plan["target_seed_papers"] = 40
    (run / "00_input" / "search_plan.json").write_text(json.dumps(search_plan))

    validate_bootstrap_stage_0_10_contract(run)
```

- [ ] **Step 5: Add regression test for any omitted raw paper**

Add this test after the legacy target test:

```python
def test_validate_bootstrap_contract_rejects_missing_raw_seed_paper(tmp_path):
    run = tmp_path / "run"
    raw_ids = [f"2501.{idx:05d}" for idx in range(60)]
    selected_ids = raw_ids[:-1]
    _write_valid_bootstrap_contract(run, ids=raw_ids)
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps(
            [
                {"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"}
                for arxiv_id in selected_ids
            ]
        )
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(raw_ids),
                "selected_total": len(selected_ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_pool.json must contain every paper kept by bulk search" in str(error)
    else:
        raise AssertionError("expected missing raw seed paper failure")
```

- [ ] **Step 6: Update existing truncated-pool assertion**

In `test_validate_bootstrap_contract_rejects_truncated_large_seed_pool`, replace the expected error assertion:

```python
assert "must contain at least 200 papers when bulk search kept 220" in str(error)
```

With:

```python
assert "paper_pool.json must contain every paper kept by bulk search" in str(error)
```

- [ ] **Step 7: Run the new/changed tests and verify failures**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_auto_research_runner_cli.py::test_run_stage_1_dispatches_query_planner_and_requires_pool_report \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_ignores_legacy_target_seed_papers \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_rejects_missing_raw_seed_paper \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_rejects_truncated_large_seed_pool \
  -v
```

Expected: FAIL before implementation. At minimum, the Stage 1 prompt assertion and missing-paper assertion should fail under the old contract.

- [ ] **Step 8: Commit failing tests**

```bash
git add tests/test_auto_research_runner_cli.py
git commit -m "test: require stage1 keep all seed papers"
```

---

### Task 2: Enforce Keep-All in Runner Code

**Files:**
- Modify: `scripts/run_auto_research.py`
- Test: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Add a helper for raw seed IDs**

Add this helper after `_seed_pool_kept_count`:

```python
def _seed_pool_ids(seed_pool: dict[str, Any]) -> list[str]:
    papers = seed_pool.get("papers")
    if isinstance(papers, dict):
        return [str(arxiv_id) for arxiv_id in papers.keys()]
    if isinstance(papers, list):
        ids: list[str] = []
        for item in papers:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and item.get("arxiv_id"):
                ids.append(str(item["arxiv_id"]))
            else:
                raise RuntimeError("seed_pool_raw.json papers list entries must be strings or include arxiv_id")
        return ids
    raise RuntimeError("seed_pool_raw.json must include papers as an object or list")
```

- [ ] **Step 2: Remove target-seed validation from bootstrap contract**

Inside `validate_bootstrap_stage_0_10_contract`, remove this line:

```python
target_seed_papers = _bootstrap_target_seed_papers(search_plan)
```

After `raw_kept_count = _seed_pool_kept_count(seed_pool)`, add:

```python
raw_seed_ids = _seed_pool_ids(seed_pool)
if len(raw_seed_ids) != raw_kept_count:
    raise RuntimeError(
        "seed_pool_raw.json total_kept must match the number of papers in papers"
    )
```

- [ ] **Step 3: Replace capped pool-size validation with exact ID validation**

Replace this block:

```python
required_pool_count = min(target_seed_papers, raw_kept_count)
if len(paper_ids) < required_pool_count:
    raise RuntimeError(
        f"paper_pool.json must contain at least {required_pool_count} papers when bulk search kept "
        f"{raw_kept_count}; got {len(paper_ids)}"
    )
```

With:

```python
if set(paper_ids) != set(raw_seed_ids):
    missing = sorted(set(raw_seed_ids) - set(paper_ids))
    extra = sorted(set(paper_ids) - set(raw_seed_ids))
    raise RuntimeError(
        "paper_pool.json must contain every paper kept by bulk search; "
        f"missing={missing[:10]}, extra={extra[:10]}, "
        f"raw_kept={len(raw_seed_ids)}, selected={len(paper_ids)}"
    )
```

- [ ] **Step 4: Remove target_seed_papers report requirement and aspect coverage gate**

Delete this block:

```python
if int(candidate_report.get("target_seed_papers", -1)) != target_seed_papers:
    raise RuntimeError("candidate_pool_report.json target_seed_papers must match search_plan.json")
per_aspect_selected = candidate_report.get("per_aspect_selected")
if not isinstance(per_aspect_selected, dict):
    raise RuntimeError("candidate_pool_report.json must include per_aspect_selected counts")
covered_aspects = [
    aspect_id
    for aspect_id in aspect_ids
    if int(per_aspect_selected.get(aspect_id, 0) or 0) > 0
]
required_aspect_coverage = min(4, len(aspect_ids))
if raw_kept_count >= target_seed_papers and len(covered_aspects) < required_aspect_coverage:
    raise RuntimeError(
        "candidate_pool_report.json must show non-zero selection from at least "
        f"{required_aspect_coverage} search aspects when bulk search kept {raw_kept_count}"
    )
```

Replace it with:

```python
per_aspect_selected = candidate_report.get("per_aspect_selected")
if per_aspect_selected is not None and not isinstance(per_aspect_selected, dict):
    raise RuntimeError("candidate_pool_report.json per_aspect_selected must be an object when present")
selection_policy = candidate_report.get("selection_policy")
if selection_policy is not None and selection_policy != "keep_all_bulk_search_results":
    raise RuntimeError("candidate_pool_report.json selection_policy must be keep_all_bulk_search_results")
```

- [ ] **Step 5: Update Stage 1 prompt**

In `run_stage_1`, replace:

```python
"Build a stratified 02_paper_pool/paper_pool.json and paper_pool.csv.",
"Write 02_paper_pool/candidate_pool_report.json with raw_kept, target_seed_papers, selected_total, and per_aspect_selected.",
```

With:

```python
"Build 02_paper_pool/paper_pool.json and paper_pool.csv from every paper in seed_pool_raw['papers']; do not downselect.",
"Write 02_paper_pool/candidate_pool_report.json with raw_kept, selected_total, selection_policy='keep_all_bulk_search_results', and optional per_aspect_selected={}.",
```

- [ ] **Step 6: Remove obsolete target helper if unused**

After the validation change, run:

```bash
rg -n "_bootstrap_target_seed_papers|DEFAULT_TARGET_SEED_PAPERS|target_seed_papers" scripts/run_auto_research.py
```

If `_bootstrap_target_seed_papers` and `DEFAULT_TARGET_SEED_PAPERS` are only used for obsolete config writing, remove `_bootstrap_target_seed_papers` entirely and remove `DEFAULT_TARGET_SEED_PAPERS`.

In `start_new_run`, remove this line from the `run_config.json` payload:

```python
"target_seed_papers": DEFAULT_TARGET_SEED_PAPERS,
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_auto_research_runner_cli.py::test_run_stage_1_dispatches_query_planner_and_requires_pool_report \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_ignores_legacy_target_seed_papers \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_rejects_missing_raw_seed_paper \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_rejects_truncated_large_seed_pool \
  tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_accepts_real_discovery_shape \
  -v
```

Expected: PASS.

- [ ] **Step 8: Commit runner implementation**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "fix: keep all stage1 seed papers"
```

---

### Task 3: Update Active Agent Instructions and Skills

**Files:**
- Modify: `.codex/agents/query_planner.toml`
- Modify: `.agents/skills/query-planning/SKILL.md`
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`
- Modify: `.codex/config.toml`
- Optionally modify: `README.md`

- [ ] **Step 1: Update query planner agent instructions**

In `.codex/agents/query_planner.toml`, replace:

```text
3. Add top-level target_seed_papers=200.
4. Add global_negative_keywords (3–8) that exclude noise across all aspects.
5. If user_queries / user_keywords were supplied, include them verbatim in the most relevant aspect.
6. Write 00_input/search_plan.json per the skill schema.
```

With:

```text
3. Add global_negative_keywords (3–8) that exclude noise across all aspects.
4. If user_queries / user_keywords were supplied, include them verbatim in the most relevant aspect.
5. Write 00_input/search_plan.json per the skill schema.
```

- [ ] **Step 2: Update query-planning skill output requirements**

In `.agents/skills/query-planning/SKILL.md`, replace:

```text
- Include top-level `"target_seed_papers": 200`; Stage 1 uses this to build the stratified candidate pool.
```

With:

```text
- Do not include `target_seed_papers`; Stage 1 keeps every paper returned by the bulk search relevance gates.
```

In the JSON example, remove:

```json
"target_seed_papers": 200,
```

- [ ] **Step 3: Update orchestrator budget and cap policy**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, replace the budget line:

```text
target_seed_papers = 200  # Stage 1 candidate pool target
```

With:

```text
Stage 1 paper policy: keep every paper returned by bulk_normal_start_search
```

Replace the current cap policy paragraph with:

```text
**Cap policy:** Stage 1 does not apply a paper-count cap after `bulk_normal_start_search`. The raw kept papers from `01_seed_pool/seed_pool_raw.json` are copied into `02_paper_pool/paper_pool.json` and `.csv` without downselection. Stage 6 keeps every paper meeting the acceptance rules; Stage 7 promotes every paper with `final_score >= min_promote_score`. Quality drops out via relevance gates and scoring, not Stage 1 truncation.
```

Replace Stage 1c with:

```text
**1c. Build the pool.** Save the raw response as `01_seed_pool/seed_pool_raw.json`. Build `02_paper_pool/paper_pool.{json,csv}` from every paper in `seed_pool_raw["papers"]`:
- Do not downselect to a fixed target.
- Do not stratify or round-robin papers out of the pool.
- Preserve every arXiv ID kept by `bulk_normal_start_search`.

Write `02_paper_pool/candidate_pool_report.json`:
```json
{
  "raw_kept": 391,
  "selected_total": 391,
  "selection_policy": "keep_all_bulk_search_results",
  "per_aspect_selected": {}
}
```

Stop if the pool has < 40 papers after a broad retry (topic too narrow or search failed).
```

- [ ] **Step 4: Update config comments**

In `.codex/config.toml`, replace:

```text
# Budgets (target_seed_papers=200, max_expansion_gaps=5, max_expansion_rounds=1,
```

With:

```text
# Budgets (max_expansion_gaps=5, max_expansion_rounds=1,
```

Replace:

```text
# definitions. After Stage 1 there is NO paper-count cap — Stages 6 and 7
# filter by relevance only.
```

With:

```text
# definitions. Stage 1 keeps every paper returned by bulk_normal_start_search;
# Stages 6 and 7 filter by relevance only.
```

- [ ] **Step 5: Check for remaining active old instructions**

Run:

```bash
rg -n "target_seed_papers|stratified|downselect|selected papers from the raw bulk-search|150–200 paper candidate pool|Build a stratified" \
  .codex .agents README.md scripts tests
```

Expected: No active instruction still asks Stage 1 to cap/downselect. Test names or regression fixtures may mention legacy `target_seed_papers` only when proving it is ignored.

- [ ] **Step 6: Commit instruction updates**

```bash
git add .codex/agents/query_planner.toml .agents/skills/query-planning/SKILL.md .agents/skills/auto-research-orchestrator/SKILL.md .codex/config.toml README.md
git commit -m "docs: remove stage1 target seed cap instructions"
```

If `README.md` was not modified, omit it from `git add`.

---

### Task 4: Run Verification

**Files:**
- No planned source edits unless verification exposes a real issue.

- [ ] **Step 1: Run focused runner tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader test suite**

Run:

```bash
PYTHONPATH=. pytest
```

Expected: PASS. If unrelated existing tests fail, capture exact failing tests and error messages in the final report without masking them.

- [ ] **Step 3: Check working tree scope**

Run:

```bash
git status --short
```

Expected: Only intended source/test/docs changes plus pre-existing unrelated dirty files. Do not stage or revert unrelated files such as `swarn_research_mcp/config/deep_config.json`, `.graphify_python`, `.graphifyignore`, `sample.json`, `tests/test.ipynb`, `tests/test.py`, or `tests/test_2.py` unless the user explicitly asks.

- [ ] **Step 4: Final commit if verification required fixes**

If verification required additional fixes, commit only those files:

```bash
git add <changed intended files>
git commit -m "fix: align stage1 keep-all verification"
```

If no additional fixes were needed after Task 3, skip this commit.

---

## Self-Review Notes

- Spec coverage: runner prompt, validation, active skills, config comments, and tests are covered.
- Placeholder scan: no unresolved placeholder markers or unspecified test steps remain in this plan.
- Scope control: this plan removes only the Stage 1 downselect. It does not remove search-tool filtering inside `bulk_normal_start_search`, does not inject manual flagship papers, and does not alter existing run artifacts.
