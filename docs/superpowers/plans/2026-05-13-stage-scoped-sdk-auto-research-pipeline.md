# Stage-Scoped SDK Auto-Research Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-big Stage 0-10 bootstrap SDK session with runner-owned, stage-scoped SDK calls, strict artifact validation, and parallel execution for independent paper/gap stages.

**Architecture:** `scripts/run_auto_research.py` remains the durable control plane: it owns stage order, state, retries, validation, and deterministic merges. Codex SDK sessions become small workers for bounded stage/shard tasks only. The immediate Stage 7 failure is fixed by running `paper_ranker` as its own SDK stage and rejecting runs that do not produce complete score artifacts.

**Tech Stack:** Python 3.11, existing `sdk.codex.run_one_shot_sync`, existing `.codex/agents/*.toml` contracts, existing MCP search/metadata/markdown tools exposed to Codex sessions, pytest.

---

## Why This Plan Exists

The failed run `research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-131400` showed a systemic control-plane bug:

- Stage 0-10 ran inside one long SDK Codex child.
- The child skipped the intended `paper_ranker` contract.
- It hardcoded five promoted IDs and wrote only `07_scoring/promoted_papers.json`.
- It did not write `07_scoring/paper_scores.csv` or `07_scoring/promotion_candidates.csv`.
- The parent accepted the run because Stage 7's primary artifact was only `promoted_papers.json`.

Root cause:

```text
Too much work in one SDK context + weak parent validation = silent pipeline corruption.
```

Target design:

```text
main Codex session
  -> Python durable runner
    -> deterministic stages where possible
    -> small SDK stage/shard workers where judgment/extraction is needed
    -> strict validation after every stage
```

---

## Desired Stage Ownership

| Stage | Owner | Parallel? | Notes |
|---|---|---:|---|
| 0 create run | Python | no | Create folders, `run_config.json`, `run_log.csv`. |
| 1a query plan | SDK `query_planner` | no | Only writes `00_input/search_plan.json`. |
| 1b search + pool | SDK or Python/MCP wrapper | no | Calls `bulk_normal_start_search` once, writes stratified pool/report. Prefer SDK first because MCP tools are already available there. |
| 2 weak evidence | SDK `weak_evidence_extractor` | yes | Shard `paper_pool` by `shard_size_papers`. |
| 3 weak graph | SDK `weak_graph_extractor` + Python merge | yes | Shard fragments, then deterministic merge. |
| 4 knowledge base snapshot | Python | no | Deterministic if the KB schema is stable enough. |
| 5 gap detection | SDK `knowledge_gap_detector` | no | One bounded judgment task. |
| 6 expansion | SDK `paper_expander` + Python merge | yes | One shard per gap. |
| 7 scoring | SDK `paper_ranker` + Python validation | no | Fixes current bug. Must write all score artifacts. |
| 8 markdown fetch | SDK or Python/MCP wrapper | yes or no | Per promoted paper; SDK is acceptable because it only calls the MCP markdown tool. |
| 9 pageindex | SDK `paper_indexer` | yes | Per promoted paper or small shards. |
| 10 verified evidence | SDK `verified_evidence_extractor` | yes | Per promoted paper or small shards; Python validates grounding. |

Do not implement Stages 11-18 in this plan except where the handler list must include the new Stage 0-10 handlers before existing Stage 11-18 logic.

---

## Files

Modify:

- `scripts/run_auto_research.py`
  - Add stage-scoped handlers for Stages 0-10.
  - Replace `bootstrap_new_run()` one-big SDK child with runner-owned Stage 0-10 execution.
  - Add Stage 7 artifact validation.
  - Add helper functions for loading paper IDs, validating CSVs, and strict stage resumes.
- `tests/test_auto_research_runner_cli.py`
  - Add Stage 7 validation tests.
  - Add bootstrap split tests.
- `tests/test_auto_research_runner_dispatch.py`
  - Add tests that stage-scoped SDK calls use small prompts and expected outputs.
- `.agents/skills/auto-research-orchestrator/SKILL.md`
  - Update Stage 0-10 instructions: no one-shot bootstrap worker; runner owns every stage.
  - Update Stage 7 primary artifacts.
- `.codex/agents/paper_ranker.toml`
  - Tighten output rules and explicitly forbid writing only `promoted_papers.json`.

Create:

- `tests/fixtures/stage7/` only if needed for reusable CSV fixtures. Prefer inline temporary files in tests unless repeated fixtures become clearer.

Do not modify:

- `swarn_research_mcp/research_book.py` unless a later test proves Stage 18 depends on new Stage 7 fields.
- Existing research run artifacts except in manual experiments. Tests must use `tmp_path`.

---

## Core Contracts

### Stage 7 Required Outputs

Stage 7 is valid only when all three files exist:

```text
07_scoring/paper_scores.csv
07_scoring/promotion_candidates.csv
07_scoring/promoted_papers.json
```

`paper_scores.csv` must contain one row per `02_paper_pool/paper_pool.json` paper.

Required `paper_scores.csv` columns:

```text
arxiv_id
topic_relevance
graph_centrality
citation_or_influence
recency
implementation_impact
chapter_need
knowledge_gap_boost
final_score
```

`promotion_candidates.csv` must contain the same IDs as `paper_scores.csv`, sorted by descending `final_score`.

`promoted_papers.json` must contain every score row with `final_score >= min_promote_score`.

Fallback rule:

```text
If zero papers meet min_promote_score, promoted_papers.json may contain exactly the top-scored paper.
```

No other truncation is allowed.

---

## Task 1: Add Stage 7 Validation, Fixing the Current Failure Mode First

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`
- Modify: `.codex/agents/paper_ranker.toml`

### Goal

Make the old bad state impossible to accept:

```text
promoted_papers.json exists
paper_scores.csv missing
promotion_candidates.csv missing
```

### Steps

- [ ] **Step 1: Write a failing test for missing Stage 7 score files**

Add this test to `tests/test_auto_research_runner_cli.py` near the existing bootstrap contract tests:

```python
def test_validate_bootstrap_contract_rejects_stage7_without_score_files(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    (run / "07_scoring" / "paper_scores.csv").unlink()
    (run / "07_scoring" / "promotion_candidates.csv").unlink()

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_scores.csv" in str(error)
    else:
        raise AssertionError("expected missing Stage 7 score files failure")
```

Update `_write_valid_bootstrap_contract(run)` so it creates valid Stage 7 score files:

```python
score_header = (
    "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
    "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
)
score_rows = "".join(
    f"{arxiv_id},0.8,0.5,0.2,0.8,0.5,0.5,0.0,{0.9 if arxiv_id == promoted_id else 0.1}\n"
    for arxiv_id in ids
)
(run / "07_scoring" / "paper_scores.csv").write_text(score_header + score_rows)
(run / "07_scoring" / "promotion_candidates.csv").write_text(score_header + score_rows)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_rejects_stage7_without_score_files -v
```

Expected: FAIL because current validation only requires `promoted_papers.json`.

- [ ] **Step 3: Add Stage 7 artifacts to `PRIMARY_ARTIFACTS`**

In `scripts/run_auto_research.py`, change:

```python
"7": ("07_scoring/promoted_papers.json",),
```

to:

```python
"7": (
    "07_scoring/paper_scores.csv",
    "07_scoring/promotion_candidates.csv",
    "07_scoring/promoted_papers.json",
),
```

- [ ] **Step 4: Add CSV helpers**

Add near `_paper_pool_ids()`:

```python
STAGE_7_SCORE_COLUMNS = (
    "arxiv_id",
    "topic_relevance",
    "graph_centrality",
    "citation_or_influence",
    "recency",
    "implementation_impact",
    "chapter_need",
    "knowledge_gap_boost",
    "final_score",
)


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise RuntimeError(f"missing required bootstrap artifact: {display_path}")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"{path.name} must contain at least one row")
    return rows


def _float_score(row: dict[str, str], *, path_name: str) -> float:
    try:
        return float(row.get("final_score", ""))
    except ValueError as error:
        raise RuntimeError(f"{path_name} final_score must be numeric for {row.get('arxiv_id')}") from error
```

- [ ] **Step 5: Add `validate_stage_7_outputs()`**

Add this function near `validate_bootstrap_stage_0_10_contract()`:

```python
def validate_stage_7_outputs(
    run_dir: Path,
    *,
    paper_ids: list[str],
    min_promote_score: float = 0.45,
) -> None:
    score_rows = _load_csv_rows(run_dir / "07_scoring" / "paper_scores.csv")
    candidate_rows = _load_csv_rows(run_dir / "07_scoring" / "promotion_candidates.csv")

    for path_name, rows in (
        ("paper_scores.csv", score_rows),
        ("promotion_candidates.csv", candidate_rows),
    ):
        missing_columns = [column for column in STAGE_7_SCORE_COLUMNS if column not in rows[0]]
        if missing_columns:
            raise RuntimeError(f"{path_name} missing columns: {missing_columns}")
        row_ids = [str(row.get("arxiv_id", "")).strip() for row in rows]
        if any(not arxiv_id for arxiv_id in row_ids):
            raise RuntimeError(f"{path_name} contains a row without arxiv_id")
        if set(row_ids) != set(paper_ids):
            raise RuntimeError(
                f"{path_name} must score exactly every paper_pool paper; "
                f"expected {len(set(paper_ids))}, got {len(set(row_ids))}"
            )

    candidate_scores = [_float_score(row, path_name="promotion_candidates.csv") for row in candidate_rows]
    if candidate_scores != sorted(candidate_scores, reverse=True):
        raise RuntimeError("promotion_candidates.csv must be sorted by descending final_score")

    score_by_id = {
        str(row["arxiv_id"]).strip(): _float_score(row, path_name="paper_scores.csv")
        for row in score_rows
    }
    expected_promoted = [
        arxiv_id
        for arxiv_id, score in sorted(score_by_id.items(), key=lambda item: item[1], reverse=True)
        if score >= min_promote_score
    ]
    if not expected_promoted and score_by_id:
        expected_promoted = [max(score_by_id.items(), key=lambda item: item[1])[0]]

    promoted = _load_json(run_dir / "07_scoring" / "promoted_papers.json")
    promoted_ids = _promoted_ids(promoted)
    if promoted_ids != expected_promoted:
        raise RuntimeError(
            "promoted_papers.json must contain exactly every paper above "
            f"min_promote_score={min_promote_score}; expected {expected_promoted}, got {promoted_ids}"
        )
```

- [ ] **Step 6: Call Stage 7 validation from bootstrap validation**

Inside `validate_bootstrap_stage_0_10_contract()`, after `paper_ids = _paper_pool_ids(paper_pool)` and after candidate pool validation, add:

```python
    validate_stage_7_outputs(run_dir, paper_ids=paper_ids)
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_rejects_stage7_without_score_files tests/test_auto_research_runner_cli.py::test_validate_bootstrap_contract_accepts_real_discovery_shape -v
```

Expected: both PASS.

- [ ] **Step 8: Update docs/contracts**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, update Stage 7 primary artifact row from:

```markdown
| 7  | `07_scoring/promoted_papers.json` |
```

to:

```markdown
| 7  | `07_scoring/paper_scores.csv` + `07_scoring/promotion_candidates.csv` + `07_scoring/promoted_papers.json` |
```

In `.codex/agents/paper_ranker.toml`, add this hard rule:

```text
Hard rules:
- You must write all three output files.
- Never write only promoted_papers.json.
- Every paper_pool arxiv_id must appear exactly once in paper_scores.csv and promotion_candidates.csv.
- promotion_candidates.csv must be sorted by final_score descending.
```

- [ ] **Step 9: Run full tests and commit**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
env PYTHONPATH=. pytest tests/ -v
git diff --check -- scripts/run_auto_research.py tests/test_auto_research_runner_cli.py .agents/skills/auto-research-orchestrator/SKILL.md .codex/agents/paper_ranker.toml
```

Expected:

```text
all tests pass
git diff --check has no output
```

Commit only the touched files:

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py .agents/skills/auto-research-orchestrator/SKILL.md .codex/agents/paper_ranker.toml
git commit -m "fix: require complete stage 7 scoring artifacts"
```

---

## Task 2: Add Runner-Owned Stage 0-10 Handler Skeleton

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

### Goal

Make the parent runner own Stage 0-10 order instead of asking one SDK child to do all of it.

### Steps

- [ ] **Step 1: Add a test that topic runs call stage handlers directly**

Add this test to `tests/test_auto_research_runner_cli.py`:

```python
def test_main_topic_all_uses_stage_scoped_bootstrap_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    calls = []

    def fake_start_run(topic, phase):
        run = tmp_path / "research_runs" / "demo-run"
        run.mkdir(parents=True)
        calls.append(("0", topic, phase))
        return "demo-run"

    def fake_stage(stage):
        def run(run_dir, **kwargs):
            calls.append((stage, run_dir.name))
        return run

    monkeypatch.setattr("scripts.run_auto_research.start_new_run", fake_start_run)
    for stage in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "12.5", "13", "14", "15", "16", "17", "18"):
        monkeypatch.setattr(f"scripts.run_auto_research.run_stage_{stage.replace('.', '_')}", fake_stage(stage))

    rc = main(["--topic", "Demo topic", "--phase", "all", "--executor", "sdk", "--max-workers", "20"])

    assert rc == 0
    assert calls[:11] == [
        ("0", "Demo topic", "all"),
        ("1", "demo-run"),
        ("2", "demo-run"),
        ("3", "demo-run"),
        ("4", "demo-run"),
        ("5", "demo-run"),
        ("6", "demo-run"),
        ("7", "demo-run"),
        ("8", "demo-run"),
        ("9", "demo-run"),
        ("10", "demo-run"),
    ]
```

If monkeypatching `"run_stage_12_5"` is awkward because the function name already exists as `run_stage_12_5`, adapt only the patch loop, not the production naming.

- [ ] **Step 2: Run the failing test**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_main_topic_all_uses_stage_scoped_bootstrap_handlers -v
```

Expected: FAIL because `main()` still calls `bootstrap_new_run()`.

- [ ] **Step 3: Add `start_new_run()`**

Add this function near `bootstrap_new_run()`:

```python
def slugify_topic(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:80] or "research"


def start_new_run(topic: str, phase: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{slugify_topic(topic)}-{timestamp}"
    run_id = base
    counter = 2
    while (RUNS_ROOT / run_id).exists():
        run_id = f"{base}-{counter}"
        counter += 1
    run_dir = RUNS_ROOT / run_id
    for rel in (
        "00_input",
        "01_seed_pool",
        "02_paper_pool",
        "03_overviews/semantic_scholar",
        "04_weak_evidence",
        "05_weak_graph/fragments",
        "06_expansion",
        "07_scoring",
        "08_full_markdown",
        "09_pageindex/trees",
        "09_pageindex/nodes",
        "10_verified_evidence",
        "11_verified_graph/fragments",
        "12_taxonomy",
        "13_chapter_packs/book",
        "13_chapter_packs/families",
        "13_chapter_packs/methods",
        "14_chapters/book",
        "14_chapters/families",
        "14_chapters/methods",
        "15_verification/book",
        "15_verification/families",
        "15_verification/methods",
        "16_book",
        "17_learning_suggestions",
    ):
        (run_dir / rel).mkdir(parents=True, exist_ok=True)
    (run_dir / "00_input" / "topic.md").write_text(topic.strip() + "\n")
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "topic": topic,
                "phase": phase,
                "target_seed_papers": DEFAULT_TARGET_SEED_PAPERS,
                "min_promote_score": 0.45,
                "created_at": now_iso(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    append_run_log(run_dir, "0", "completed", "run_config and directories created")
    return run_id
```

- [ ] **Step 4: Add placeholder Stage 1-10 handler names**

Add temporary handlers below `start_new_run()`:

```python
def run_stage_1(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 1 split handler is implemented in Task 3")


def run_stage_2(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 2 split handler is implemented in Task 4")


def run_stage_3(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 3 split handler is implemented in Task 4")


def run_stage_4(run_dir: Path) -> None:
    raise NotImplementedError("Stage 4 split handler is implemented in Task 5")


def run_stage_5(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 5 split handler is implemented in Task 5")


def run_stage_6(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 6 split handler is implemented in Task 5")


def run_stage_7(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 7 split handler is implemented in Task 6")


def run_stage_8(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 8 split handler is implemented in Task 7")


def run_stage_9(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 9 split handler is implemented in Task 7")


def run_stage_10(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    raise NotImplementedError("Stage 10 split handler is implemented in Task 7")
```

- [ ] **Step 5: Change `main()` to build handlers from Stage 1**

Replace the topic bootstrap block:

```python
    run_id = args.run_id
    if run_id is None:
        run_id = bootstrap_new_run(args.topic, args.phase, executor=args.executor)
```

with:

```python
    run_id = args.run_id
    topic_bootstrap = run_id is None
    if run_id is None:
        run_id = start_new_run(args.topic, args.phase)
```

Change handler lists:

```python
    bootstrap_handlers = [
        ("1", run_stage_1),
        ("2", run_stage_2),
        ("3", run_stage_3),
        ("4", run_stage_4),
        ("5", run_stage_5),
        ("6", run_stage_6),
        ("7", run_stage_7),
        ("8", run_stage_8),
        ("9", run_stage_9),
        ("10", run_stage_10),
    ]
    draft_handlers = [
        ("11", run_stage_11),
        ("12", run_stage_12),
        ("12.5", run_stage_12_5),
        ("13", run_stage_13),
    ]
```

Then set handlers:

```python
    if args.phase == "draft":
        handlers = (bootstrap_handlers + draft_handlers) if topic_bootstrap else draft_handlers
    elif args.phase == "write":
        handlers = write_handlers
    else:
        handlers = (bootstrap_handlers if topic_bootstrap else []) + draft_handlers + write_handlers
```

- [ ] **Step 6: Run the focused test**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_main_topic_all_uses_stage_scoped_bootstrap_handlers -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
git diff --check -- scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "refactor: route bootstrap through stage handlers"
```

---

## Task 3: Implement Stage 1 as Query Planning + Search/Pool Contract

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

### Goal

Stage 1 becomes a bounded SDK call plus explicit validation. It must not become a long multi-stage child.

### Steps

- [ ] **Step 1: Add tests for Stage 1 SDK prompt**

Add:

```python
def test_run_stage_1_dispatches_query_planner_and_requires_pool_report(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend(specs)
        (run / "00_input").mkdir(parents=True, exist_ok=True)
        (run / "01_seed_pool").mkdir(parents=True, exist_ok=True)
        (run / "02_paper_pool").mkdir(parents=True, exist_ok=True)
        aspects = [
            {
                "aspect_id": f"aspect_{idx}",
                "normal_queries": [f"normal {idx}"],
                "survey_queries": [f"survey {idx}"],
                "positive_keywords": [f"keyword {idx}"],
            }
            for idx in range(4)
        ]
        (run / "00_input" / "search_plan.json").write_text(
            json.dumps({"topic": "Demo", "target_seed_papers": 200, "aspects": aspects})
        )
        bulk_path = run / "01_seed_pool" / "bulk_search_results_123.json"
        ids = [f"2501.{idx:05d}" for idx in range(40)]
        bulk_path.write_text(json.dumps({"papers": ids}))
        (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
            json.dumps({"papers": {arxiv_id: "abstract" for arxiv_id in ids}, "total_kept": 40, "output_path": str(bulk_path)})
        )
        (run / "02_paper_pool" / "paper_pool.json").write_text(
            json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
        )
        (run / "02_paper_pool" / "paper_pool.csv").write_text("arxiv_id\n" + "\n".join(ids) + "\n")
        (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
            json.dumps({"raw_kept": 40, "target_seed_papers": 200, "selected_total": 40, "per_aspect_selected": {f"aspect_{idx}": 10 for idx in range(4)}})
        )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_1(run)

    assert len(calls) == 1
    assert calls[0].stage == "1"
    assert calls[0].agent == "query_planner"
    assert "Run Stage 1 only" in calls[0].prompt
    assert "candidate_pool_report.json" in calls[0].prompt
```

- [ ] **Step 2: Implement `run_stage_1()`**

Replace the placeholder with:

```python
def run_stage_1(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "1"):
        append_run_log(run_dir, "1", "skipped", "paper pool already present")
        return
    topic_path = run_dir / "00_input" / "topic.md"
    topic = topic_path.read_text().strip() if topic_path.exists() else run_dir.name
    spec = ShardSpec(
        stage="1",
        shard_id="seed-pool",
        agent="query_planner",
        model="gpt-5.4",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                *DIRECT_SHARD_RULES,
                "Run Stage 1 only.",
                f"run_id={run_dir.name}",
                f"topic={topic}",
                "Follow .codex/agents/query_planner.toml and .agents/skills/query-planning/SKILL.md.",
                "Write 00_input/search_plan.json.",
                "Call bulk_normal_start_search exactly once with query-planner unions.",
                "Write 01_seed_pool/seed_pool_raw.json and preserve bulk_search_results_<timestamp>.json in 01_seed_pool/.",
                "Build a stratified 02_paper_pool/paper_pool.json and paper_pool.csv.",
                "Write 02_paper_pool/candidate_pool_report.json with raw_kept, target_seed_papers, selected_total, and per_aspect_selected.",
                "Do not run Stage 2 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=[
            "00_input/search_plan.json",
            "01_seed_pool/seed_pool_raw.json",
            "02_paper_pool/paper_pool.json",
            "02_paper_pool/paper_pool.csv",
            "02_paper_pool/candidate_pool_report.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor, timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS)
    paper_pool = _load_json(run_dir / "02_paper_pool" / "paper_pool.json")
    paper_ids = _paper_pool_ids(paper_pool)
    if len(paper_ids) < MIN_BOOTSTRAP_PAPER_POOL:
        raise RuntimeError(f"Stage 1 produced too few papers: {len(paper_ids)}")
    append_run_log(run_dir, "1", "completed", f"paper pool contains {len(paper_ids)} papers")
```

- [ ] **Step 3: Run tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_run_stage_1_dispatches_query_planner_and_requires_pool_report -v
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat: run stage 1 as scoped sdk task"
```

---

## Task 4: Implement Parallel Stage 2 and Stage 3

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

### Goal

Weak evidence and weak graph extraction run as small SDK shards, not inside a monolithic bootstrap context.

### Steps

- [ ] **Step 1: Add helper for paper pool IDs**

If not already available globally, add:

```python
def load_paper_pool_arxiv_ids(run_dir: Path) -> list[str]:
    return _paper_pool_ids(_load_json(run_dir / "02_paper_pool" / "paper_pool.json"))
```

- [ ] **Step 2: Implement `run_stage_2()`**

Replace placeholder:

```python
def run_stage_2(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "04_weak_evidence" / f"{arxiv_id}.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 5), start=1):
        shard_id = f"weak-evidence-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="2",
                shard_id=shard_id,
                agent="weak_evidence_extractor",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/weak_evidence_extractor.toml",
                    run_dir.name,
                    "2",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[f"04_weak_evidence/{arxiv_id}.json" for arxiv_id in chunk],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    still_missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "04_weak_evidence" / f"{arxiv_id}.json").exists()
    ]
    if still_missing:
        raise RuntimeError(f"Stage 2 missing weak evidence: {still_missing[:10]}")
    append_run_log(run_dir, "2", "completed", f"weak evidence generated for {len(paper_ids)} papers")
```

- [ ] **Step 3: Implement `run_stage_3()`**

Use existing weak graph agent and deterministic merge logic. If no merge helper exists, add:

```python
def merge_weak_graph_fragments(run_dir: Path) -> None:
    fragments_dir = run_dir / "05_weak_graph" / "fragments"
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edge_keys: set[tuple[str, str, str]] = set()
    edges: list[dict[str, Any]] = []
    for path in sorted(fragments_dir.glob("*.json")):
        data = json.loads(path.read_text())
        for node in data.get("nodes", []):
            node_id = str(node.get("id", "")).strip()
            if not node_id:
                raise RuntimeError(f"weak graph node missing id in {path}")
            nodes_by_id.setdefault(node_id, node)
        for edge in data.get("edges", []):
            key = (
                str(edge.get("source", "")),
                str(edge.get("target", "")),
                str(edge.get("relation", "")),
            )
            if not all(key):
                raise RuntimeError(f"weak graph edge missing source/target/relation in {path}")
            if key not in edge_keys:
                edge_keys.add(key)
                edges.append(edge)
    if not nodes_by_id:
        raise RuntimeError("Stage 3 produced no weak graph nodes")
    output = run_dir / "05_weak_graph" / "weak_global_graph.json"
    output.write_text(json.dumps({"nodes": list(nodes_by_id.values()), "edges": edges}, indent=2, sort_keys=True) + "\n")
```

Then replace placeholder:

```python
def run_stage_3(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    if primary_artifact_exists(run_dir, "3"):
        append_run_log(run_dir, "3", "skipped", "weak graph already present")
        return
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "05_weak_graph" / "fragments" / f"{arxiv_id}.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 5), start=1):
        shard_id = f"weak-graph-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="3",
                shard_id=shard_id,
                agent="weak_graph_extractor",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/weak_graph_extractor.toml",
                    run_dir.name,
                    "3",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[f"05_weak_graph/fragments/{arxiv_id}.json" for arxiv_id in chunk],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    merge_weak_graph_fragments(run_dir)
    append_run_log(run_dir, "3", "completed", "weak graph merged")
```

- [ ] **Step 4: Add focused tests**

Add tests that monkeypatch `run_shards` and verify:

```text
Stage 2 chunks 12 papers into 3 specs with max chunk size 5.
Stage 3 chunks 12 papers into 3 specs and writes weak_global_graph.json after fragments exist.
```

Use existing test patterns from Stage 11 dispatch tests.

- [ ] **Step 5: Run and commit**

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
env PYTHONPATH=. pytest tests/test_auto_research_runner_dispatch.py -v
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat: run weak evidence and graph as parallel sdk stages"
```

---

## Task 5: Implement Stages 4, 5, and 6

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

### Goal

Knowledge-base snapshot is deterministic; gap detection is one bounded SDK task; paper expansion is parallel per gap with deterministic merge.

### Steps

- [ ] **Step 1: Implement Stage 4 as scoped SDK first**

If deterministic KB parsing is not already stable, keep Stage 4 as one SDK task:

```python
def run_stage_4(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "4"):
        append_run_log(run_dir, "4", "skipped", "knowledge base snapshot already present")
        return
    spec = ShardSpec(
        stage="4",
        shard_id="knowledge-base",
        agent="knowledge_base_reader",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_base_reader.toml",
            run_dir.name,
            "4",
            "knowledge-base",
            {},
        ),
        expected_outputs=["06_expansion/known_concepts_snapshot.json"],
    )
    run_shards(run_dir, [spec], executor=DEFAULT_EXECUTOR)
    append_run_log(run_dir, "4", "completed", "knowledge base snapshot written")
```

If tests reveal `run_stage_4()` needs `executor`, add `executor: str = DEFAULT_EXECUTOR` and pass it to `run_shards`.

- [ ] **Step 2: Implement Stage 5**

```python
def run_stage_5(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "5"):
        append_run_log(run_dir, "5", "skipped", "knowledge gap report already present")
        return
    spec = ShardSpec(
        stage="5",
        shard_id="knowledge-gaps",
        agent="knowledge_gap_detector",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_gap_detector.toml",
            run_dir.name,
            "5",
            "knowledge-gaps",
            {},
        ),
        expected_outputs=[
            "06_expansion/knowledge_gap_report.json",
            "06_expansion/expansion_need_queue.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor)
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    append_run_log(run_dir, "5", "completed", f"knowledge gap report written; queue_items={len(items)}")
```

- [ ] **Step 3: Implement Stage 6 merge helpers**

Add:

```python
def load_expansion_gap_items(run_dir: Path) -> list[dict[str, Any]]:
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    if not isinstance(items, list):
        raise RuntimeError("expansion_need_queue.json items must be a list")
    return [item for item in items if isinstance(item, dict)]
```

For the first implementation, require each expander shard to write:

```text
06_expansion/shards/{shard_id}_accepted_candidates.csv
06_expansion/shards/{shard_id}_rejected_candidates.csv
06_expansion/shards/{shard_id}_round.json
```

Add merge helper:

```python
def merge_expansion_shards(run_dir: Path, shard_ids: list[str]) -> None:
    expansion_dir = run_dir / "06_expansion"
    shards_dir = expansion_dir / "shards"
    accepted_rows: list[str] = []
    rejected_rows: list[str] = []
    round_items: list[dict[str, Any]] = []
    accepted_header = "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
    rejected_header = "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
    for shard_id in shard_ids:
        round_path = shards_dir / f"{shard_id}_round.json"
        if round_path.exists():
            data = json.loads(round_path.read_text())
            if isinstance(data, dict):
                round_items.extend(data.get("items", []) or [])
        for path, rows in (
            (shards_dir / f"{shard_id}_accepted_candidates.csv", accepted_rows),
            (shards_dir / f"{shard_id}_rejected_candidates.csv", rejected_rows),
        ):
            if path.exists():
                lines = path.read_text().splitlines()
                rows.extend(line for line in lines[1:] if line.strip())
    (expansion_dir / "accepted_candidates.csv").write_text(accepted_header + "\n".join(accepted_rows) + ("\n" if accepted_rows else ""))
    (expansion_dir / "rejected_candidates.csv").write_text(rejected_header + "\n".join(rejected_rows) + ("\n" if rejected_rows else ""))
    (expansion_dir / "expansion_round_01.json").write_text(
        json.dumps({"status": "completed" if round_items else "skipped", "items": round_items}, indent=2, sort_keys=True) + "\n"
    )
```

- [ ] **Step 4: Implement Stage 6**

```python
def run_stage_6(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    if primary_artifact_exists(run_dir, "6"):
        append_run_log(run_dir, "6", "skipped", "expansion round already present")
        return
    gap_items = load_expansion_gap_items(run_dir)
    if not gap_items:
        expansion_dir = run_dir / "06_expansion"
        (expansion_dir / "expansion_round_01.json").write_text(json.dumps({"status": "skipped", "items": []}, indent=2) + "\n")
        (expansion_dir / "accepted_candidates.csv").write_text("arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n")
        (expansion_dir / "rejected_candidates.csv").write_text("arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n")
        append_run_log(run_dir, "6", "skipped", "no expansion gaps")
        return
    shard_ids = []
    specs = []
    for idx, item in enumerate(gap_items, start=1):
        shard_id = f"expansion-{idx:03d}"
        shard_ids.append(shard_id)
        specs.append(
            ShardSpec(
                stage="6",
                shard_id=shard_id,
                agent="paper_expander",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/paper_expander.toml",
                    run_dir.name,
                    "6",
                    shard_id,
                    {"gap_item": item},
                ),
                expected_outputs=[
                    f"06_expansion/shards/{shard_id}_round.json",
                    f"06_expansion/shards/{shard_id}_accepted_candidates.csv",
                    f"06_expansion/shards/{shard_id}_rejected_candidates.csv",
                ],
            )
        )
    run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    merge_expansion_shards(run_dir, shard_ids)
    append_run_log(run_dir, "6", "completed", f"expanded {len(gap_items)} gaps")
```

- [ ] **Step 5: Add tests and commit**

Add tests for:

```text
Stage 6 writes skipped files when queue is empty.
Stage 6 dispatches one shard per gap when queue has items.
```

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat: split knowledge gaps and expansion bootstrap stages"
```

---

## Task 6: Implement Stage 7 as a Separate SDK `paper_ranker`

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`
- Modify: `.codex/agents/paper_ranker.toml`

### Goal

Fix the current Stage 7 error at the process level: `paper_ranker` gets its own small SDK context and is validated immediately.

### Steps

- [ ] **Step 1: Add test for scoped Stage 7 prompt**

Add:

```python
def test_run_stage_7_dispatches_paper_ranker_and_validates_scores(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    ids = ["1.1", "1.2"]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend(specs)
        header = (
            "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
            "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
        )
        rows = "1.1,1,1,1,1,1,1,0,0.9\n1.2,0,0,0,0,0,0,0,0.1\n"
        (run / "07_scoring" / "paper_scores.csv").write_text(header + rows)
        (run / "07_scoring" / "promotion_candidates.csv").write_text(header + rows)
        (run / "07_scoring" / "promoted_papers.json").write_text(
            json.dumps({"promoted_papers": [{"arxiv_id": "1.1", "final_score": 0.9}]})
        )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_7(run)

    assert len(calls) == 1
    assert calls[0].agent == "paper_ranker"
    assert "Run Stage 7 scoring only" in calls[0].prompt
    assert "paper_scores.csv" in calls[0].prompt
```

- [ ] **Step 2: Implement `run_stage_7()`**

Replace placeholder:

```python
def run_stage_7(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "7"):
        paper_ids = load_paper_pool_arxiv_ids(run_dir)
        validate_stage_7_outputs(run_dir, paper_ids=paper_ids)
        append_run_log(run_dir, "7", "skipped", "scoring artifacts already present")
        return
    spec = ShardSpec(
        stage="7",
        shard_id="paper-ranker",
        agent="paper_ranker",
        model="gpt-5.4-mini",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                *DIRECT_SHARD_RULES,
                "Run Stage 7 scoring only.",
                f"run_id={run_dir.name}",
                "Follow .codex/agents/paper_ranker.toml exactly.",
                "Read 02_paper_pool/paper_pool.json, 04_weak_evidence/*.json, 05_weak_graph/weak_global_graph.json, and 06_expansion/knowledge_gap_report.json.",
                "Write all three outputs: 07_scoring/paper_scores.csv, 07_scoring/promotion_candidates.csv, 07_scoring/promoted_papers.json.",
                "Do not fetch markdown.",
                "Do not run Stage 8 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=[
            "07_scoring/paper_scores.csv",
            "07_scoring/promotion_candidates.csv",
            "07_scoring/promoted_papers.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor)
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    validate_stage_7_outputs(run_dir, paper_ids=paper_ids)
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    append_run_log(run_dir, "7", "completed", f"{len(paper_ids)} scored, {len(promoted_ids)} promoted")
```

- [ ] **Step 3: Update `paper_ranker.toml`**

Add explicit file contract:

```text
Validation-sensitive outputs:
- paper_scores.csv must include every paper_pool arxiv_id exactly once.
- promotion_candidates.csv must include the same rows sorted by final_score descending.
- promoted_papers.json must include every row with final_score >= min_promote_score.
- Do not cap the promoted list.
- If zero rows meet the threshold, promote exactly the top-scored paper as fallback.
```

- [ ] **Step 4: Run tests and commit**

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_run_stage_7_dispatches_paper_ranker_and_validates_scores -v
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
env PYTHONPATH=. pytest tests/ -v
git diff --check -- scripts/run_auto_research.py tests/test_auto_research_runner_cli.py .codex/agents/paper_ranker.toml
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py .codex/agents/paper_ranker.toml
git commit -m "feat: run paper ranking as scoped sdk stage"
```

---

## Task 7: Implement Stages 8, 9, and 10 as Scoped Tasks

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

### Goal

Markdown, page indexing, and verified evidence no longer run inside the same SDK context as scoring.

### Steps

- [ ] **Step 1: Implement Stage 8 as one bounded SDK task**

```python
def run_stage_8(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not (run_dir / "08_full_markdown" / f"{arxiv_id}.md").exists()
    ]
    if not missing:
        append_run_log(run_dir, "8", "skipped", "markdown already present")
        return
    spec = ShardSpec(
        stage="8",
        shard_id="full-markdown",
        agent="knowledge_base_reader",
        model="gpt-5.4-mini",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                *DIRECT_SHARD_RULES,
                "Run Stage 8 full markdown fetch only.",
                f"run_id={run_dir.name}",
                f"arxiv_ids={missing}",
                "For each arxiv_id, call get_paper_markdown and write 08_full_markdown/{arxiv_id}.md.",
                "Do not run Stage 9 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=[f"08_full_markdown/{arxiv_id}.md" for arxiv_id in missing],
    )
    run_shards(run_dir, [spec], executor=executor, timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS)
    append_run_log(run_dir, "8", "completed", f"markdown fetched for {len(missing)} papers")
```

Using `knowledge_base_reader` as the agent name is acceptable only if there is no dedicated markdown-fetching agent. If an implementation agent creates a dedicated `.codex/agents/full_markdown_fetcher.toml`, update tests and docs in the same task.

- [ ] **Step 2: Implement Stage 9**

```python
def run_stage_9(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not (run_dir / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 2), start=1):
        shard_id = f"pageindex-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="9",
                shard_id=shard_id,
                agent="paper_indexer",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/paper_indexer.toml",
                    run_dir.name,
                    "9",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[f"09_pageindex/trees/{arxiv_id}.tree.json" for arxiv_id in chunk],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    append_run_log(run_dir, "9", "completed", f"page indexes ready for {len(promoted_ids)} papers")
```

- [ ] **Step 3: Implement Stage 10**

```python
def run_stage_10(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not (run_dir / "10_verified_evidence" / f"{arxiv_id}.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 1), start=1):
        shard_id = f"verified-evidence-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="10",
                shard_id=shard_id,
                agent="verified_evidence_extractor",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/verified_evidence_extractor.toml",
                    run_dir.name,
                    "10",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[f"10_verified_evidence/{arxiv_id}.json" for arxiv_id in chunk],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    for arxiv_id in promoted_ids:
        evidence = _load_json(run_dir / "10_verified_evidence" / f"{arxiv_id}.json")
        claims = evidence.get("claims") if isinstance(evidence, dict) else None
        if not claims:
            raise RuntimeError(f"verified evidence for {arxiv_id} has no claims")
        for claim in claims:
            if not claim.get("source_node_id") or not claim.get("source_lines"):
                raise RuntimeError(f"verified claim for {arxiv_id} is missing source grounding")
    append_run_log(run_dir, "10", "completed", f"verified evidence ready for {len(promoted_ids)} papers")
```

- [ ] **Step 4: Add tests and commit**

Add tests that monkeypatch `run_shards` and verify:

```text
Stage 9 shards promoted IDs.
Stage 10 shards one paper at a time and validates source grounding.
```

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
env PYTHONPATH=. pytest tests/ -v
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat: split markdown indexing and verified evidence stages"
```

---

## Task 8: Remove One-Big Bootstrap Child Path

**Files:**

- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`
- Modify: `.agents/skills/deep-research-supervisor/SKILL.md` if it references old bootstrap behavior.

### Goal

No normal end-to-end path should call a single SDK child for Stage 0-10.

### Steps

- [ ] **Step 1: Make `bootstrap_new_run()` impossible to use by default**

Either delete `bootstrap_new_run()` or leave it as a legacy helper that raises:

```python
def bootstrap_new_run(*args: Any, **kwargs: Any) -> str:
    raise RuntimeError(
        "bootstrap_new_run is retired; use start_new_run plus stage-scoped handlers"
    )
```

Prefer deletion if no tests or callers remain.

- [ ] **Step 2: Update tests**

Delete tests that assert old `codex exec` bootstrap flags. Replace them with:

```python
def test_bootstrap_new_run_is_retired():
    try:
        bootstrap_new_run("Demo topic", "all")
    except RuntimeError as error:
        assert "retired" in str(error)
    else:
        raise AssertionError("expected retired bootstrap failure")
```

If `bootstrap_new_run()` is deleted, remove it from imports and skip this test.

- [ ] **Step 3: Update orchestrator docs**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, remove wording that implies a Stage 0-10 bootstrap worker exists.

Add:

```markdown
The runner must execute Stages 0-10 as separate stage handlers. Do not ask one Codex SDK session to run multiple stages from 0 through 10.
```

- [ ] **Step 4: Run tests and commit**

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py tests/test_auto_research_runner_dispatch.py -v
env PYTHONPATH=. pytest tests/ -v
git diff --check -- scripts/run_auto_research.py tests/test_auto_research_runner_cli.py .agents/skills/auto-research-orchestrator/SKILL.md
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "refactor: retire monolithic bootstrap sdk session"
```

---

## Task 9: End-to-End Smoke Test

**Files:**

- No required source changes.
- May create a new `research_runs/<topic>-<timestamp>/`.

### Goal

Prove the pipeline can start from a topic, run Stage 0-10 using stage-scoped SDK tasks, and stop with complete Stage 7 score artifacts.

### Steps

- [ ] **Step 1: Run a small real topic**

Use a narrow topic to control runtime:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py \
  --topic "real-time speech-to-speech language models for voice assistants" \
  --phase draft \
  --executor sdk \
  --max-workers 20
```

Expected:

```text
runner starts at Stage 1 after creating run
Stage 2/3/9/10 use shard manifests under run_control/stages/
Stage 7 logs "<N> scored, <M> promoted"
```

- [ ] **Step 2: Inspect Stage 7 artifacts**

Replace `<run_id>`:

```bash
python - <<'PY'
import csv, json
from pathlib import Path
run = Path("research_runs/<run_id>")
pool = json.loads((run / "02_paper_pool/paper_pool.json").read_text())
pool_ids = {row["arxiv_id"] for row in pool}
scores = list(csv.DictReader((run / "07_scoring/paper_scores.csv").open()))
candidates = list(csv.DictReader((run / "07_scoring/promotion_candidates.csv").open()))
promoted = json.loads((run / "07_scoring/promoted_papers.json").read_text())["promoted_papers"]
print("pool", len(pool_ids))
print("scores", len(scores))
print("candidates", len(candidates))
print("promoted", len(promoted))
assert {row["arxiv_id"] for row in scores} == pool_ids
assert {row["arxiv_id"] for row in candidates} == pool_ids
assert promoted
PY
```

Expected: assertions pass.

- [ ] **Step 3: Inspect shard logs**

```bash
find research_runs/<run_id>/run_control/stages -maxdepth 3 -type f | sort | rg 'sdk_threads|shards'
```

Expected: Stage 2, 3, 7, 9, and 10 have visible stage/shard logs. Stage 7 should have a single `paper-ranker` shard.

- [ ] **Step 4: Commit only if source files changed during smoke fix**

If smoke testing required fixes:

```bash
env PYTHONPATH=. pytest tests/ -v
git diff --check
git add <changed source/test/doc files only>
git commit -m "fix: stabilize stage-scoped bootstrap smoke run"
```

If no source changes were needed, do not commit research run artifacts.

---

## Execution Notes For Future Agents

- The repo may have unrelated dirty files. Do not stage broad directories.
- Always stage exact file paths.
- Use `env PYTHONPATH=.` for pytest and runner commands.
- Do not use `git reset --hard` or checkout unrelated files.
- Do not delete existing user research runs.
- The first implementation checkpoint is Task 1. It fixes the current Stage 7 silent failure even before the larger split is complete.
- The largest risk is overbuilding deterministic versions of every stage. Avoid that. The goal is smaller SDK contexts plus validation, not replacing all research judgment with Python.
- Stage 7 is intentionally a separate SDK task in this plan because the user wants to try validation plus context splitting before moving scoring fully into Python.

---

## Self-Review

- Stage 7 error is covered by Task 1 and Task 6.
- One-big Stage 0-10 context is removed by Tasks 2-8.
- Parallelism is covered by Tasks 4, 5, and 7.
- Existing Stage 11-18 flow is preserved.
- No task requires changing historical research run artifacts.
- No unresolved placeholders remain in this plan.
