# Auto Research Reader Quality Contract Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the stage-contract bugs that make a mechanically completed research run produce a weak handbook, especially missing family synthesis, over-strict method gap verification, and hidden runner failures.

**Architecture:** Keep the durable Python runner and stage-scoped SDK execution model. Make narrow contract fixes in the runner, chapter packs, verifier/writer skills, and navigation artifact builder; do not do the large `run_auto_research.py` module extraction in this plan.

**Tech Stack:** Python 3, pytest, Codex skill/TOML prompts, Markdown handbook artifacts, JSON/CSV run artifacts.

---

## Review Of Proposed Fix Plan

The external review is directionally right: the latest run failed as a product because the family bridge layer was quarantined and many methods were rejected by impossible gap requirements. The most important diagnosis is that the failures are mostly stage-contract mismatches, not dispatch failures.

I would change three priorities:

1. Do the smallest reliability fixes immediately after the `passed` nesting fix. Tracebacks and locked logs reduce risk for every later rerun.
2. Do not rename method IDs or files in this plan. Method IDs are used across outline, packs, chapters, verification, manifest, and navigation. A mass rename is risky and unnecessary for reader navigation. Use display labels in `SUMMARY.md` and `sidebar.json` first.
3. Treat `partially_supported` as informational, but fix verifier instructions so family/book synthesis anchored in pack evidence is not downgraded merely because it synthesizes across sources.

This plan intentionally skips the big module extraction until the product passes a real run with useful family and method chapters.

## Target Files

- Modify: `scripts/run_auto_research.py`
  - Accept `summary.passed` as a backward-compatible pass signal.
  - Preserve exception tracebacks from shard attempts.
  - Lock `run_log.csv` writes.
  - Add deterministic per-method gap scoping in method packs.
- Modify: `swarn_research_mcp/research_book.py`
  - Improve method labels in `SUMMARY.md` and `sidebar.json` without renaming files.
- Modify: `.agents/skills/family-chapter-writing/SKILL.md`
  - Add pack-only named-entity rules for family prose and tables.
- Modify: `.codex/agents/family_chapter_writer.toml`
  - Mirror the pack-only rule where the agent receives executable instructions.
- Modify: `.agents/skills/verification/SKILL.md`
  - Add top-level `passed` to schema.
  - Add family/book synthesis support rule.
  - Change method gap coverage to read `pack.knowledge_gaps_to_explain`, not the global report.
- Modify: `.codex/agents/verifier.toml`
  - Mirror the synthesis and per-pack gap rules.
- Modify: `.agents/skills/chapter-pack-building/SKILL.md`
  - Define per-method `knowledge_gaps_to_explain` as a scoped, capped list.
- Modify: `.codex/agents/chapter_pack_builder.toml`
  - Mirror the method gap scoping contract.
- Modify: `sdk/codex_app_server/retry.py`
  - Increase overload retry budget.
- Modify: `sdk/codex_app_server/client.py`
  - Add a default notification wait deadline.
- Modify: `sdk/codex_app_server/api.py`
  - Import `ThreadStartSource` and `SortDirection`.
- Create: `.agents/skills/paper-ranking/SKILL.md`
  - Move Stage 7 scoring contract out of TOML-only documentation.
- Modify: `.codex/agents/paper_ranker.toml`
  - Point to the new skill and keep only executable deltas.
- Modify: `.codex/config.toml`
  - Remove or correct stale `max_seed_papers=50` comment.
- Modify: `.codex/agents/method_chapter_writer.toml`
  - Fix "10-section" description to "11-section".
- Test: `tests/test_auto_research_runner_cli.py`
- Test: `tests/test_research_book_artifacts.py`
- Test: `tests/test_codex_scaffold.py`
- Test: add `tests/test_codex_sdk_reliability.py`

---

### Task 1: Accept Nested Verification Pass Flags

**Files:**
- Modify: `scripts/run_auto_research.py`
- Test: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Write the failing test**

Add this test near the manifest/status tests in `tests/test_auto_research_runner_cli.py`:

```python
def test_verification_status_accepts_summary_passed_for_backward_compat():
    target = {"type": "families", "id": "evaluation_benchmarks"}
    verification = {
        "summary": {
            "passed": True,
            "claims_unsupported": 0,
            "claims_overstated": 0,
            "gaps_missing": 0,
            "form_issue_count": 0,
            "word_count": 1400,
        }
    }

    status, reason = runner._verification_status(
        target,
        verification,
        chapter_word_count=1400,
    )

    assert status == "passed"
    assert reason == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_verification_status_accepts_summary_passed_for_backward_compat -v
```

Expected: FAIL because `_verification_status()` only reads top-level `verification["passed"]`.

- [ ] **Step 3: Add a helper and use it**

In `scripts/run_auto_research.py`, add this helper above `_verification_status()`:

```python
def _verification_passed(verification: dict[str, Any]) -> bool:
    summary = verification.get("summary")
    return verification.get("passed") is True or (
        isinstance(summary, dict) and summary.get("passed") is True
    )
```

Then change:

```python
if verification.get("passed") is True:
    return "passed", ""
```

to:

```python
if _verification_passed(verification):
    return "passed", ""
```

Also change `_write_verification_summary()` row construction from:

```python
"passed": data.get("passed"),
```

to:

```python
"passed": _verification_passed(data),
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_verification_status_accepts_summary_passed_for_backward_compat tests/test_auto_research_runner_cli.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "fix: accept nested verification passed flag"
```

---

### Task 2: Preserve Shard Tracebacks And Lock Run Log Writes

**Files:**
- Modify: `scripts/run_auto_research.py`
- Test: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Write failing tests**

Add imports if absent:

```python
import csv
```

Add these tests to `tests/test_auto_research_runner_cli.py`:

```python
def test_run_single_shard_records_traceback_on_exception(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec = runner.ShardSpec(
        stage="99",
        shard_id="boom",
        agent="broken_agent",
        model="gpt-5.4-mini",
        prompt="fail",
        expected_outputs=["out.txt"],
    )

    def fail_attempt(*args, **kwargs):
        raise ValueError("specific boom")

    monkeypatch.setattr(runner, "_run_shard_attempt", fail_attempt)

    with pytest.raises(RuntimeError):
        runner._run_single_shard(run_dir, spec, max_retries=0)

    stderr = (
        run_dir
        / "run_control"
        / "shards"
        / "99"
        / "boom"
        / "boom.attempt-1.stderr.txt"
    ).read_text()
    assert "sdk_thread=n/a sdk_turn=n/a" in stderr
    assert "Traceback (most recent call last)" in stderr
    assert "ValueError: specific boom" in stderr


def test_append_run_log_writes_single_header_under_repeated_calls(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    for idx in range(20):
        runner.append_run_log(run_dir, "x", "status", f"detail {idx}")

    rows = list(csv.reader((run_dir / "run_log.csv").open()))
    assert rows[0] == ["timestamp", "stage", "status", "detail"]
    assert rows.count(["timestamp", "stage", "status", "detail"]) == 1
    assert len(rows) == 21
```

- [ ] **Step 2: Run tests to verify traceback test fails**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_run_single_shard_records_traceback_on_exception tests/test_auto_research_runner_cli.py::test_append_run_log_writes_single_header_under_repeated_calls -v
```

Expected: traceback test fails because stderr only contains exception type and message.
The `pytest.raises(RuntimeError)` assertion is intentional: `_run_single_shard()` catches the original attempt error, writes the failed attempt files, then raises `RuntimeError` after expected outputs are still missing.

- [ ] **Step 3: Add traceback capture and log lock**

In `scripts/run_auto_research.py`, add imports:

```python
import threading
import traceback
```

Add a module-level lock near constants:

```python
_RUN_LOG_LOCK = threading.Lock()
```

Replace `append_run_log()` with:

```python
def append_run_log(run_dir: Path, stage: str, status: str, detail: str) -> None:
    log_path = run_dir / "run_log.csv"
    with _RUN_LOG_LOCK:
        needs_header = not log_path.exists()
        with log_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=("timestamp", "stage", "status", "detail"))
            if needs_header:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": now_iso(),
                    "stage": stage,
                    "status": status,
                    "detail": detail,
                }
            )
```

In `_run_single_shard()`, replace the current exception branch:

```python
result = ShardAttemptResult(
    returncode=None,
    stdout="",
    stderr=f"{type(error).__name__}: {error}\n",
    executor=executor,
)
```

with:

```python
sdk_meta = getattr(error, "sdk_meta", None)
sdk_thread = sdk_meta.get("thread_id") if isinstance(sdk_meta, dict) else "n/a"
sdk_turn = sdk_meta.get("turn_id") if isinstance(sdk_meta, dict) else "n/a"
stderr = (
    f"sdk_thread={sdk_thread} sdk_turn={sdk_turn}\n"
    + "".join(traceback.format_exception(type(error), error, error.__traceback__))
)
result = ShardAttemptResult(
    returncode=None,
    stdout="",
    stderr=stderr,
    executor=executor,
)
```

Current SDK exception classes do not carry `sdk_meta`; this header still gives a stable `n/a` marker today and preserves thread/turn IDs if a future SDK error attaches them.

- [ ] **Step 4: Run focused tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_run_single_shard_records_traceback_on_exception tests/test_auto_research_runner_cli.py::test_append_run_log_writes_single_header_under_repeated_calls tests/test_auto_research_runner_cli.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "fix: preserve shard tracebacks and lock run log"
```

---

### Task 3: Make Family Writers Pack-Only

**Files:**
- Modify: `.agents/skills/family-chapter-writing/SKILL.md`
- Modify: `.codex/agents/family_chapter_writer.toml`
- Test: `tests/test_codex_scaffold.py`

- [ ] **Step 1: Write a static contract test**

Add to `tests/test_codex_scaffold.py`:

```python
def test_family_writer_contract_forbids_out_of_pack_names():
    skill = Path(".agents/skills/family-chapter-writing/SKILL.md").read_text()
    toml = Path(".codex/agents/family_chapter_writer.toml").read_text()

    required_phrases = [
        "Do not name any method, paper, library, system, model, benchmark, or dataset that is not present in the pack",
        "pack.method_ids",
        "pack.comparison_rows",
        "pack.neighbor_family_ids",
        "omit it",
    ]
    for phrase in required_phrases:
        assert phrase in skill
        assert phrase in toml
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_scaffold.py::test_family_writer_contract_forbids_out_of_pack_names -v
```

Expected: FAIL because the explicit pack-only rule is missing.

- [ ] **Step 3: Update family writing skill**

In `.agents/skills/family-chapter-writing/SKILL.md`, add these bullets under `## Hard rules`:

```markdown
- Do not name any method, paper, library, system, model, benchmark, or dataset that is not present in the pack. Allowed names are only from `pack.method_ids`, `pack.comparison_rows`, and `pack.neighbor_family_ids`.
- If a famous method or benchmark is relevant but not in the pack, omit it. Listing only the methods in the pack is correct behavior; do not add examples from memory for completeness.
- `## Main Variants` table rows must correspond exactly to `pack.method_ids`: no additions, no omissions, no renamed methods. Use titles and row values from `pack.comparison_rows`.
```

- [ ] **Step 4: Update family writer TOML**

In `.codex/agents/family_chapter_writer.toml`, add the same executable contract inside `developer_instructions` near the existing Main Variants instructions:

```text
Pack-only naming rule:
- Do not name any method, paper, library, system, model, benchmark, or dataset that is not present in the pack. Allowed names are only from pack.method_ids, pack.comparison_rows, and pack.neighbor_family_ids.
- If a famous method or benchmark is relevant but not in the pack, omit it. Listing only the methods in the pack is correct behavior; do not add examples from memory for completeness.
- The Main Variants table rows must correspond exactly to pack.method_ids: no additions, no omissions, no renamed methods. Use titles and row values from pack.comparison_rows.
```

- [ ] **Step 5: Run tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_scaffold.py::test_family_writer_contract_forbids_out_of_pack_names -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/family-chapter-writing/SKILL.md .codex/agents/family_chapter_writer.toml tests/test_codex_scaffold.py
git commit -m "docs: constrain family chapters to pack names"
```

---

### Task 4: Fix Verifier Rules For Synthesis And Per-Pack Gaps

**Files:**
- Modify: `.agents/skills/verification/SKILL.md`
- Modify: `.codex/agents/verifier.toml`
- Test: `tests/test_codex_scaffold.py`

- [ ] **Step 1: Write static contract tests**

Add to `tests/test_codex_scaffold.py`:

```python
def test_verifier_contract_allows_family_and_book_synthesis():
    skill = Path(".agents/skills/verification/SKILL.md").read_text()
    toml = Path(".codex/agents/verifier.toml").read_text()

    required_phrases = [
        "Synthesis claims for family and book chapters",
        "Do not downgrade a claim to partially_supported merely because it synthesizes across multiple cited sources",
        "all named methods are present in the pack",
    ]
    for phrase in required_phrases:
        assert phrase in skill
        assert phrase in toml


def test_verifier_contract_uses_pack_scoped_gap_list():
    skill = Path(".agents/skills/verification/SKILL.md").read_text()
    toml = Path(".codex/agents/verifier.toml").read_text()

    required_phrases = [
        "pack.knowledge_gaps_to_explain",
        "Do not load the global knowledge_gap_report as a per-chapter required checklist",
        "At most 3 method gaps are required",
        '"passed"',
    ]
    for phrase in required_phrases:
        assert phrase in skill
        assert phrase in toml
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_scaffold.py::test_verifier_contract_allows_family_and_book_synthesis tests/test_codex_scaffold.py::test_verifier_contract_uses_pack_scoped_gap_list -v
```

Expected: FAIL because the new contract text is absent.

- [ ] **Step 3: Update verification skill**

In `.agents/skills/verification/SKILL.md`, add after `### Artifact grounding`:

```markdown
### Synthesis claims for family and book chapters
Do not downgrade a claim to `partially_supported` merely because it synthesizes across multiple cited sources. For `family:*`, a synthesis sentence is `supported` when all named methods are present in the pack and each cited node exists in verified evidence or fetched source text. For `book:*`, a synthesis sentence is `supported` when every named method/family/concept is present in the chapter pack or outline and each cited node exists in verified evidence or fetched source text.

Use `partially_supported` only when the sentence combines anchored pack evidence with an extra factual assertion that is not anchored by any cited node. `partially_supported` is informational; it is not counted as `claims_unsupported`.
```

Replace the current `## Knowledge-gap coverage` text with:

```markdown
## Knowledge-gap coverage
Use the chapter pack, not the global gap report, as the required checklist.

- `method:*`: check only `pack.knowledge_gaps_to_explain`; at most 3 method gaps are required. If the pack list is empty, emit an empty `knowledge_gap_coverage` list and `gaps_missing = 0`.
- `family:*`: check only `pack.knowledge_gaps_to_explain`; family synthesis may cover gaps across methods.
- `book:*`: check only the section-specific concepts in the book pack. Do not load the global `knowledge_gap_report` as a per-chapter required checklist.

Do not load the global knowledge_gap_report as a per-chapter required checklist. Global gaps are input to pack building, not verifier obligations for every chapter.
```

In the JSON schema example, add top-level `passed` immediately after `"chapter_type"` and before `"claims"` so it is unambiguously outside `summary`:

```json
  "passed": true,
```

Keep the success rule:

```markdown
- `passed` iff `claims_unsupported == 0 AND claims_overstated == 0 AND gaps_missing == 0 AND form_issue_count == 0`.
```

- [ ] **Step 4: Update verifier TOML**

Add matching concise instructions to `.codex/agents/verifier.toml`:

```text
Synthesis claims for family and book chapters: Do not downgrade a claim to partially_supported merely because it synthesizes across multiple cited sources. For family:* all named methods must be present in the pack; for book:* all named methods/families/concepts must be present in the pack or outline. Every cited node must exist in verified evidence or fetched source text. partially_supported is informational and does not count as claims_unsupported.

Knowledge-gap coverage: use pack.knowledge_gaps_to_explain, not the global knowledge_gap_report, as the per-chapter checklist. At most 3 method gaps are required. If the pack list is empty, emit an empty knowledge_gap_coverage list and gaps_missing=0. Do not load the global knowledge_gap_report as a per-chapter required checklist.

Output must include top-level "passed" as well as summary counts.
```

- [ ] **Step 5: Run tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_scaffold.py::test_verifier_contract_allows_family_and_book_synthesis tests/test_codex_scaffold.py::test_verifier_contract_uses_pack_scoped_gap_list -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/verification/SKILL.md .codex/agents/verifier.toml tests/test_codex_scaffold.py
git commit -m "docs: align verifier with synthesis and pack-scoped gaps"
```

---

### Task 5: Scope Method Knowledge Gaps In Packs

**Files:**
- Modify: `scripts/run_auto_research.py`
- Modify: `.agents/skills/chapter-pack-building/SKILL.md`
- Modify: `.codex/agents/chapter_pack_builder.toml`
- Test: `tests/test_auto_research_runner_cli.py`
- Test: `tests/test_codex_scaffold.py`

- [ ] **Step 1: Write failing method pack test**

Add to `tests/test_auto_research_runner_cli.py` near existing method pack tests:

```python
def test_build_method_pack_scopes_knowledge_gaps_to_method_evidence(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "10_verified_evidence").mkdir(parents=True)
    (run_dir / "06_expansion").mkdir(parents=True)
    (run_dir / "10_verified_evidence" / "1234.00001.json").write_text(json.dumps({
        "claims": [
            {
                "text": "AudioMAE masks spectrogram patches before reconstruction.",
                "claim_type": "method",
                "source_node_id": "s.01",
                "source_lines": [1, 3],
            },
            {
                "text": "The encoder learns acoustic representations from mel spectrograms.",
                "claim_type": "method",
                "source_node_id": "s.02",
                "source_lines": [4, 8],
            },
        ],
        "equations": [],
        "algorithms": [],
        "limitations": [
            {
                "text": "The method depends on masked reconstruction quality.",
                "source_node_id": "s.03",
            }
        ],
    }))
    (run_dir / "06_expansion" / "knowledge_gap_report.json").write_text(json.dumps({
        "knowledge_gaps": [
            {"concept": "asr", "priority": 0.9},
            {"concept": "mel", "priority": 0.9},
            {"concept": "mel spectrogram", "priority": 0.9},
            {"concept": "masked reconstruction", "priority": 0.8},
            {"concept": "codec tokens", "priority": 0.9},
            {"concept": "full duplex dialog", "priority": 0.9},
            {"concept": "autoregressive decoding", "priority": 0.9},
        ]
    }))
    outline = {
        "families": [{"id": "fam", "title": "Fam", "method_ids": ["audiomae"]}],
        "methods": [{
            "id": "audiomae",
            "title": "AudioMAE",
            "arxiv_id": "1234.00001",
            "family_id": "fam",
            "neighbor_method_ids": [],
        }],
    }

    pack = runner._build_method_pack(run_dir, outline, outline["methods"][0])

    assert pack["knowledge_gaps_to_explain"] == [
        "mel spectrogram",
        "masked reconstruction",
    ]
    assert "asr" not in pack["knowledge_gaps_to_explain"]
    assert "mel" not in pack["knowledge_gaps_to_explain"]
```

- [ ] **Step 2: Write static skill test**

Add to `tests/test_codex_scaffold.py`:

```python
def test_chapter_pack_contract_caps_method_gap_scope():
    skill = Path(".agents/skills/chapter-pack-building/SKILL.md").read_text()
    toml = Path(".codex/agents/chapter_pack_builder.toml").read_text()

    required_phrases = [
        "Method packs must scope knowledge_gaps_to_explain to concepts actually touched by that method",
        "Cap method knowledge_gaps_to_explain at 3 concepts",
        "Do not copy the global knowledge_gap_report into every method pack",
    ]
    for phrase in required_phrases:
        assert phrase in skill
        assert phrase in toml
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_build_method_pack_scopes_knowledge_gaps_to_method_evidence tests/test_codex_scaffold.py::test_chapter_pack_contract_caps_method_gap_scope -v
```

Expected: FAIL because `_build_method_pack()` currently trusts `method.knowledge_gaps_to_explain` and the docs do not state the cap.

- [ ] **Step 4: Implement deterministic gap scoping**

In `scripts/run_auto_research.py`, add helpers near `_first_text()` or the method-pack helper section:

```python
def _gap_concept_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("concept", "name", "gap", "topic", "title"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _knowledge_gap_candidates(run_dir: Path) -> list[str]:
    report = _read_json_or_empty(run_dir / "06_expansion" / "knowledge_gap_report.json")
    raw_items: list[Any] = []
    for key in ("knowledge_gaps", "gaps", "confusing_concepts", "missing_prerequisites"):
        value = report.get(key)
        if isinstance(value, list):
            raw_items.extend(value)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        concept = _gap_concept_text(item)
        normalized = concept.lower()
        if concept and normalized not in seen:
            seen.add(normalized)
            out.append(concept)
    return sorted(out, key=lambda concept: len(concept.split()), reverse=True)


def _concept_matches_evidence(concept: str, evidence_text: str) -> bool:
    escaped = re.escape(concept.lower()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<!\w){escaped}s?(?!\w)", evidence_text) is not None


def _method_gap_scope(run_dir: Path, method: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    explicit = [_gap_concept_text(item) for item in method.get("knowledge_gaps_to_explain") or []]
    explicit = [item for item in explicit if item]
    if explicit:
        return explicit[:3]

    evidence_text_parts: list[str] = []
    for claim in evidence.get("claims") or []:
        if isinstance(claim, dict):
            evidence_text_parts.append(str(claim.get("text") or ""))
    for key in ("equations", "algorithms", "hyperparameters", "complexity", "datasets", "artifacts", "benchmarks", "metrics", "baselines", "results", "limitations"):
        for item in evidence.get(key) or []:
            if isinstance(item, dict):
                evidence_text_parts.extend(str(value) for value in item.values() if isinstance(value, str))
            elif isinstance(item, str):
                evidence_text_parts.append(item)
    evidence_text = " ".join(evidence_text_parts).lower()

    scoped: list[str] = []
    for concept in _knowledge_gap_candidates(run_dir):
        if _concept_matches_evidence(concept, evidence_text):
            scoped.append(concept)
        if len(scoped) >= 3:
            break
    return scoped
```

In `_build_method_pack()`, replace:

```python
"knowledge_gaps_to_explain": method.get("knowledge_gaps_to_explain") or [],
```

with:

```python
"knowledge_gaps_to_explain": _method_gap_scope(run_dir, method, evidence),
```

- [ ] **Step 5: Update chapter pack skill and TOML**

In `.agents/skills/chapter-pack-building/SKILL.md`, add under `## Method pack (load-bearing)`:

```markdown
Method packs must scope `knowledge_gaps_to_explain` to concepts actually touched by that method's verified evidence. Prefer `outline.methods[*].knowledge_gaps_to_explain` when present, otherwise intersect `knowledge_gap_report` concepts with the method's verified-evidence claim and structured text. Cap method `knowledge_gaps_to_explain` at 3 concepts. Do not copy the global `knowledge_gap_report` into every method pack.
```

Add the same concise rule to `.codex/agents/chapter_pack_builder.toml`:

```text
Method packs must scope knowledge_gaps_to_explain to concepts actually touched by that method's verified evidence. Prefer outline.methods[*].knowledge_gaps_to_explain when present, otherwise intersect knowledge_gap_report concepts with the method's verified-evidence claim and structured text. Cap method knowledge_gaps_to_explain at 3 concepts. Do not copy the global knowledge_gap_report into every method pack.
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_build_method_pack_scopes_knowledge_gaps_to_method_evidence tests/test_codex_scaffold.py::test_chapter_pack_contract_caps_method_gap_scope tests/test_auto_research_runner_cli.py -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/run_auto_research.py .agents/skills/chapter-pack-building/SKILL.md .codex/agents/chapter_pack_builder.toml tests/test_auto_research_runner_cli.py tests/test_codex_scaffold.py
git commit -m "fix: scope method knowledge gaps in packs"
```

---

### Task 6: Improve Reader Navigation Labels Without Renaming Files

**Files:**
- Modify: `swarn_research_mcp/research_book.py`
- Test: `tests/test_research_book_artifacts.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_research_book_artifacts.py`:

```python
def test_summary_method_label_includes_slug_when_title_and_id_differ(tmp_path):
    outline = {
        "book_sections": [],
        "parts": [{"id": "part", "title": "Part", "family_ids": ["fam"]}],
        "families": [{"id": "fam", "title": "Family", "method_ids": ["vq-vae-semantic-discretization"]}],
        "methods": [{
            "id": "vq-vae-semantic-discretization",
            "title": "MaskGCT: Zero-Shot Text-to-Speech with Masked Generative Codec Transformer",
            "family_id": "fam",
        }],
    }

    summary = research_book._build_summary(outline)

    assert "MaskGCT: Zero-Shot Text-to-Speech" in summary
    assert "vq-vae-semantic-discretization" in summary


def test_sidebar_method_label_includes_slug_when_title_and_id_differ(tmp_path):
    outline = {
        "book_sections": [],
        "parts": [{"id": "part", "title": "Part", "family_ids": ["fam"]}],
        "families": [{"id": "fam", "title": "Family", "method_ids": ["probabilistic-residual-vector-quantization"]}],
        "methods": [{
            "id": "probabilistic-residual-vector-quantization",
            "title": "CLaM-TTS: Improving Neural Codec Language Modeling",
            "family_id": "fam",
        }],
    }

    sidebar = research_book._build_sidebar(outline)
    label = sidebar["items"][1]["children"][0]["children"][0]["title"]

    assert "CLaM-TTS" in label
    assert "probabilistic-residual-vector-quantization" in label
```

Use existing import style in the file; if `research_book` is imported with a different alias, match that alias instead of adding a duplicate import.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env PYTHONPATH=. pytest tests/test_research_book_artifacts.py::test_summary_method_label_includes_slug_when_title_and_id_differ tests/test_research_book_artifacts.py::test_sidebar_method_label_includes_slug_when_title_and_id_differ -v
```

Expected: FAIL because labels currently show only the paper title.

- [ ] **Step 3: Add display-label helper**

In `swarn_research_mcp/research_book.py`, add near `_build_summary()`:

```python
def _method_display_title(method: dict[str, Any], method_id: str) -> str:
    title = str(method.get("title") or method_id)
    readable_id = method_id.replace("-", " ")
    if readable_id.lower() in title.lower() or method_id.lower() in title.lower():
        return title
    return f"{title} ({method_id})"
```

In `_build_summary()`, replace both instances of:

```python
method['title']
```

inside method links with:

```python
_method_display_title(method, method_id)
```

In `_build_sidebar()`, replace both method child title values:

```python
method["title"]
```

with:

```python
_method_display_title(method, method_id)
```

- [ ] **Step 4: Run tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_research_book_artifacts.py::test_summary_method_label_includes_slug_when_title_and_id_differ tests/test_research_book_artifacts.py::test_sidebar_method_label_includes_slug_when_title_and_id_differ tests/test_research_book_artifacts.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add swarn_research_mcp/research_book.py tests/test_research_book_artifacts.py
git commit -m "fix: show method slugs in navigation labels"
```

---

### Task 7: Harden SDK Retry And Notification Waiting

**Files:**
- Modify: `sdk/codex_app_server/retry.py`
- Modify: `sdk/codex_app_server/client.py`
- Modify: `sdk/codex_app_server/async_client.py`
- Test: add `tests/test_codex_sdk_reliability.py`

- [ ] **Step 1: Write retry tests**

Create `tests/test_codex_sdk_reliability.py`:

```python
import time

import pytest

from sdk.codex_app_server import retry as retry_module
from sdk.codex_app_server.client import AppServerClient


def test_retry_on_overload_defaults_are_long_enough(monkeypatch):
    sleeps = []
    attempts = {"count": 0}

    class FakeOverload(Exception):
        pass

    def fake_is_retryable(exc):
        return isinstance(exc, FakeOverload)

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 6:
            raise FakeOverload("server_overloaded")
        return "ok"

    monkeypatch.setattr(retry_module, "is_retryable_error", fake_is_retryable)
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    assert retry_module.retry_on_overload(flaky, jitter_ratio=0.0) == "ok"
    assert attempts["count"] == 6
    assert max(sleeps) <= 30.0
    assert sum(sleeps) >= 20.0


def test_next_notification_raises_timeout(monkeypatch):
    client = AppServerClient()
    calls = []

    def fake_read_message(timeout_s=None):
        calls.append(timeout_s)
        raise TimeoutError("no message")

    monkeypatch.setattr(client, "_read_message", fake_read_message)

    with pytest.raises(TimeoutError):
        client.next_notification(timeout_s=0.01)
    assert calls == [0.01]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_sdk_reliability.py -v
```

Expected: FAIL because retry defaults are too small and `next_notification(timeout_s=...)` does not exist.

- [ ] **Step 3: Increase retry defaults**

In `sdk/codex_app_server/retry.py`, change defaults:

```python
max_attempts: int = 6,
initial_delay_s: float = 2.0,
max_delay_s: float = 30.0,
```

Make the same default changes in `request_with_retry_on_overload()` in both `sdk/codex_app_server/client.py` and `sdk/codex_app_server/async_client.py`.

- [ ] **Step 4: Add notification timeout parameter**

In `sdk/codex_app_server/client.py`, change:

```python
def next_notification(self) -> Notification:
```

to:

```python
def next_notification(self, timeout_s: float | None = 600.0) -> Notification:
```

Change `_read_message()` from:

```python
def _read_message(self) -> dict[str, JsonValue]:
```

to:

```python
def _read_message(self, timeout_s: float | None = None) -> dict[str, JsonValue]:
```

Import `select` at the top of the file. Before `readline()`, add:

```python
if timeout_s is not None:
    ready, _, _ = select.select([self._proc.stdout], [], [], timeout_s)
    if not ready:
        raise TimeoutError(f"timed out waiting {timeout_s}s for app-server message")
```

This repository runs on Linux, so `select.select()` on the app-server stdout pipe is acceptable. Leave existing `_request_raw()` calls unchanged so normal requests still block as before. If CI later runs this SDK test on Windows, replace this with a thread-backed timeout fallback before enabling the Windows job.

In `next_notification()`, call:

```python
msg = self._read_message(timeout_s=timeout_s)
```

In `sdk/codex_app_server/async_client.py`, change:

```python
async def next_notification(self) -> Notification:
    return await self._call_sync(self._sync.next_notification)
```

to:

```python
async def next_notification(self, timeout_s: float | None = 600.0) -> Notification:
    return await self._call_sync(self._sync.next_notification, timeout_s)
```

- [ ] **Step 5: Run tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_sdk_reliability.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sdk/codex_app_server/retry.py sdk/codex_app_server/client.py sdk/codex_app_server/async_client.py tests/test_codex_sdk_reliability.py
git commit -m "fix: harden sdk retry and notification waits"
```

---

### Task 8: Fix SDK Annotation Imports

**Files:**
- Modify: `sdk/codex_app_server/api.py`
- Test: `tests/test_codex_sdk_reliability.py`

- [ ] **Step 1: Add failing type-hints test**

Append to `tests/test_codex_sdk_reliability.py`:

```python
import typing

from sdk.codex_app_server.api import AsyncCodex, Codex


def test_sdk_public_type_hints_resolve():
    assert typing.get_type_hints(Codex.thread_start)
    assert typing.get_type_hints(Codex.thread_list)
    assert typing.get_type_hints(AsyncCodex.thread_start)
    assert typing.get_type_hints(AsyncCodex.thread_list)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_sdk_reliability.py::test_sdk_public_type_hints_resolve -v
```

Expected: FAIL with `NameError` for `ThreadStartSource` or `SortDirection`.

- [ ] **Step 3: Import missing generated types**

In `sdk/codex_app_server/api.py`, add these names to the existing `.generated.v2_all` import list:

```python
SortDirection,
ThreadStartSource,
```

- [ ] **Step 4: Run test**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_sdk_reliability.py::test_sdk_public_type_hints_resolve tests/test_codex_sdk_reliability.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sdk/codex_app_server/api.py tests/test_codex_sdk_reliability.py
git commit -m "fix: import sdk annotation types"
```

---

### Task 9: Add Paper Ranking Skill And Clean Drift

**Files:**
- Create: `.agents/skills/paper-ranking/SKILL.md`
- Modify: `.codex/agents/paper_ranker.toml`
- Modify: `.codex/config.toml`
- Modify: `.codex/agents/method_chapter_writer.toml`
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`
- Test: `tests/test_codex_scaffold.py`

- [ ] **Step 1: Write static drift test**

Add to `tests/test_codex_scaffold.py`:

```python
def test_paper_ranker_has_companion_skill_and_budget_docs_are_current():
    skill_path = Path(".agents/skills/paper-ranking/SKILL.md")
    assert skill_path.exists()

    skill = skill_path.read_text()
    ranker = Path(".codex/agents/paper_ranker.toml").read_text()
    config = Path(".codex/config.toml").read_text()
    method_writer = Path(".codex/agents/method_chapter_writer.toml").read_text()
    orchestrator = Path(".agents/skills/auto-research-orchestrator/SKILL.md").read_text()

    assert "final_score = 0.35*topic_relevance" in skill
    assert "Follow .agents/skills/paper-ranking/SKILL.md" in ranker
    assert "max_seed_papers=50" not in config
    assert "11-section template" in method_writer
    assert "Two-pass execution (Codex sub-agent model bug workaround)" not in orchestrator
    assert "Two-pass execution" not in orchestrator
    assert "relaunch codex with --model gpt-5.4" not in orchestrator
    assert "Now relaunch codex" not in orchestrator
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_scaffold.py::test_paper_ranker_has_companion_skill_and_budget_docs_are_current -v
```

Expected: FAIL because paper-ranking skill is missing and drift remains.

- [ ] **Step 3: Create paper-ranking skill**

Create `.agents/skills/paper-ranking/SKILL.md`:

```markdown
---
name: paper-ranking
description: Score every candidate paper and promote every paper above the relevance threshold with no upper cap.
---

# Paper Ranking

## Inputs
- `02_paper_pool/paper_pool.json`
- `04_weak_evidence/*.json`
- `05_weak_graph/weak_global_graph.json`
- `06_expansion/knowledge_gap_report.json`
- `min_promote_score` (default `0.45`)

## Outputs
Write all three files under `07_scoring/`:
- `paper_scores.csv`
- `promotion_candidates.csv`
- `promoted_papers.json`

## Formula
Clamp each component to `[0, 1]`:

```text
final_score = 0.35*topic_relevance
            + 0.20*graph_centrality
            + 0.15*citation_or_influence
            + 0.10*recency
            + 0.10*implementation_impact
            + 0.10*chapter_need
```

Add `knowledge_gap_boost` up to `+0.20` only when all are true:
- `paper.source == "knowledge_gap_expansion"`
- the paper's gap priority is at least `0.70`
- `paper.candidate_role` is `foundational` or `survey`

## Components
- `topic_relevance = weak_evidence.importance_score_1_to_5 / 5`
- `graph_centrality = node_degree / max_degree` in `weak_global_graph`
- `citation_or_influence = log1p(citationCount) / log1p(10000)`, default `0`
- `recency = clamp((year - 2018) / 8, 0, 1)`, default `0.5`
- `implementation_impact = 1` if the paper introduces a method/codebase used by another pool paper, else `0`
- `chapter_need = 1` if core/support entry for dominant graph community, `0.5` if support, else `0`

## Hard Rules
- Every `paper_pool` arxiv_id appears exactly once in `paper_scores.csv`.
- `promotion_candidates.csv` contains every scored paper sorted by descending `final_score`.
- `promoted_papers.json` includes every paper with `final_score >= min_promote_score`.
- Do not cap the promoted list.
- If zero papers meet the threshold, promote exactly the top-scored paper as fallback.
- Never write only `promoted_papers.json`.

## Output Schema
`paper_scores.csv` columns:
`arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,implementation_impact,chapter_need,knowledge_gap_boost,final_score`

`promoted_papers.json`:

```json
{
  "promoted_papers": [
    {"arxiv_id": "", "final_score": 0.0, "reason": "", "is_gap_paper": false}
  ]
}
```

## Success
Return `ok: P scored, N promoted (threshold={min_promote_score})`.
```

- [ ] **Step 4: Update ranker TOML**

In `.codex/agents/paper_ranker.toml`, add at the top of `developer_instructions`:

```text
Follow .agents/skills/paper-ranking/SKILL.md.
```

Keep the existing formula text unless a later cleanup task deliberately shortens TOMLs.

- [ ] **Step 5: Clean drift**

In `.codex/config.toml`, replace the stale comment:

```toml
# Budgets (max_seed_papers=50, max_expansion_gaps=5, max_expansion_rounds=1,
```

with:

```toml
# Budgets (target_seed_papers=200, max_expansion_gaps=5, max_expansion_rounds=1,
```

In `.codex/agents/method_chapter_writer.toml`, change:

```toml
description = "Write a shard of method chapters using Book_style's 10-section template. Reproduce equations and pseudocode verbatim from the pack."
```

to:

```toml
description = "Write a shard of method chapters using Book_style's 11-section template. Reproduce equations and pseudocode verbatim from the pack."
```

In `.agents/skills/auto-research-orchestrator/SKILL.md`, delete the `## Two-pass execution (Codex sub-agent model bug workaround)` section and its operator workflow/status lines. Keep the durable runner instructions at the top and the `phase=draft|write|all` input definitions.

- [ ] **Step 6: Run tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_codex_scaffold.py::test_paper_ranker_has_companion_skill_and_budget_docs_are_current -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .agents/skills/paper-ranking/SKILL.md .codex/agents/paper_ranker.toml .codex/config.toml .codex/agents/method_chapter_writer.toml .agents/skills/auto-research-orchestrator/SKILL.md tests/test_codex_scaffold.py
git commit -m "docs: add paper ranking skill and clean drift"
```

---

### Task 10: Re-Verify Existing Real Run Without Full Re-Crawl

**Files:**
- Existing run: `research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624`
- No code files unless this task exposes a bug.

- [ ] **Step 1: Capture baseline pass counts**

Run:

```bash
env PYTHONPATH=. python - <<'PY'
import csv
from pathlib import Path
run = Path("research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624")
summary = run / "15_verification" / "verification_summary.csv"
counts = {}
with summary.open() as handle:
    for row in csv.DictReader(handle):
        key = (row["target_type"], row["passed"])
        counts[key] = counts.get(key, 0) + 1
print(counts)
PY
```

Expected: prints current pass/fail counts.

- [ ] **Step 2: Regenerate manifest and final artifacts only**

Run:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py \
  --run-id real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624 \
  --phase all \
  --resume \
  --from-stage 16 \
  --executor sdk \
  --max-workers 20
```

Expected: Stage 16/17/18 complete. `evaluation_benchmarks`, or any chapter with only nested `summary.passed`, is no longer excluded for `excluded_verification_failed`.

- [ ] **Step 3: Rebuild packs and reverify without rewriting chapters**

Run:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py \
  --run-id real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624 \
  --phase all \
  --resume \
  --from-stage 13 \
  --executor sdk \
  --max-workers 20
```

If Stage 14 skips existing chapter files, this reruns pack building, verification, manifest, and final artifacts. Expected: many methods previously excluded only for irrelevant global gaps now pass.

- [ ] **Step 4: Rewrite families only**

If family pass count is still below 7, remove only family chapter and verification files:

```bash
find research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624/14_chapters/families -name '*.md' -delete
find research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624/15_verification/families -name '*_verification.json' -delete
env PYTHONPATH=. python scripts/run_auto_research.py \
  --run-id real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624 \
  --phase all \
  --resume \
  --from-stage 14 \
  --executor sdk \
  --max-workers 20
```

Expected target: at least 7 of 10 family chapters pass. If fewer pass, inspect the first failed family verification JSON and fix the narrow contract issue before another rerun.

- [ ] **Step 5: Validate final book**

Run:

```bash
env PYTHONPATH=. python -m swarn_research_mcp.research_book \
  research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624 \
  --validate
env PYTHONPATH=. pytest tests/ -v
```

Expected:
- Validator exits 0. Warnings for quarantined chapters are acceptable.
- Full test suite passes.
- `16_book/SUMMARY.md` and `16_book/sidebar.json` show clearer method labels.
- Family pass count is materially improved.

- [ ] **Step 6: Commit only if code/docs changed during verification**

If verification exposed and fixed extra bugs:

```bash
git status --short
git add scripts/run_auto_research.py swarn_research_mcp/research_book.py tests/test_auto_research_runner_cli.py tests/test_research_book_artifacts.py
git commit -m "fix: address reader quality verification fallout"
```

Only stage files that were actually changed by the fallout fix. Do not commit generated `research_runs/` artifacts unless the repository already tracks the specific files intentionally.

---

## Deferred Work

Do not do these until this plan passes a real run:

- Extract `shard_runner.py`, `chapter_packs.py`, and `chapter_manifest.py`.
- Rename method IDs or move method chapter files.
- Expand `.agents/knowledge_base.md`.
- Merge `deep-research-supervisor` into `AGENTS.md`.
- Remove `partially_supported` from verifier schema.

## Final Success Criteria

1. Full test suite passes with `env PYTHONPATH=. pytest tests/ -v`.
2. Direct validation exits 0:
   ```bash
   env PYTHONPATH=. python -m swarn_research_mcp.research_book research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624 --validate
   ```
3. Existing voice-assistant run has:
   - At least 7 passing family chapters, or a documented concrete blocker in `NEEDS_REVIEW.md`.
   - Method pass count materially higher than 31/149 after pack-scoped gap verification.
   - No family excluded only because of nested `summary.passed`.
   - No family writer hallucinated named methods outside its pack after rewrite.
4. `16_book/SUMMARY.md` is navigable: method labels show both paper title and mechanism slug when they differ.
5. Shard stderr logs include Python tracebacks for runner/SDK exceptions.
6. `run_log.csv` has one header and no interleaved/corrupt rows after parallel stage runs.
