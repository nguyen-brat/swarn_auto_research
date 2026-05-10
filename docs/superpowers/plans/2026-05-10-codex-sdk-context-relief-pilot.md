# Codex SDK Context-Relief Pilot — `query_planner` only

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate whether routing one stage through `AsyncCodex.thread_start()` (instead of full sub-agent dispatch) actually buys the two things we want — orchestrator context relief and explicit model selection. Build the helper, instrument it, run side-by-side against the existing `.toml` agent, and decide whether to migrate further.

**Architecture:** Add `run_one_shot` and `run_one_shot_batch` helpers to `sdk/codex.py`. Pilot with `query_planner` only (smallest, lowest-risk single-shot stage). Keep `.codex/agents/query_planner.toml` in place during the pilot — both paths run, outputs and instrumentation logged. Decide migration go/no-go after the pilot.

**Tech Stack:** Python 3.11 (asyncio, pytest), Codex SDK (`AsyncCodex`).

**Spec:** `docs/superpowers/specs/2026-05-10-codex-book-style-alignment-design.md` §7

**Out of scope:**
- `outline_planner` and `chapter_manifest_builder` — they read multiple files and edit chapter files in place. Not migration candidates.
- `knowledge_gap_detector`, `paper_ranker` — defer to a follow-up plan after this pilot proves the approach.
- TOML deletion — defer until after the pilot's go/no-go.

---

## File Map

**Modify:**
- `sdk/codex.py` — add `run_one_shot`, `run_one_shot_batch`, instrumentation logger
- `.agents/skills/auto-research-orchestrator/SKILL.md` — document the pilot (no rules changed for stages other than query_planner)

**Create:**
- `swarn_research_mcp/config/sdk_prompts/query_planner.md` — system prompt lifted from the TOML
- `tests/test_sdk_run_one_shot.py`
- `docs/sdk_pilot_report.md` — instrumented results from the pilot run

**Delete:**
- nothing (TOML deletion deferred to post-pilot)

---

## Task 1: Add `run_one_shot` to sdk/codex.py

**Files:**
- Test: `tests/test_sdk_run_one_shot.py` (create)
- Modify: `sdk/codex.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sdk_run_one_shot.py
from __future__ import annotations
import asyncio
import importlib.util
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "sdk" / "codex.py"


def _load():
    spec = importlib.util.spec_from_file_location("sdk_codex_pilot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeThread:
    def __init__(self, responses):
        self._responses = list(responses)
        self.run = AsyncMock(side_effect=self._next)

    async def _next(self, _prompt):
        result = MagicMock()
        result.final_response = self._responses.pop(0)
        return result


class _FakeCodex:
    def __init__(self, thread):
        self._thread = thread
        self.thread_start = AsyncMock(return_value=thread)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_returns_string_when_no_schema():
    m = _load()
    fake = _FakeCodex(_FakeThread(["hello"]))
    async def go():
        with patch.object(m, "AsyncCodex", return_value=fake):
            return await m.run_one_shot(prompt="p", model="gpt-5.4-mini", system="s")
    assert asyncio.run(go()) == "hello"


def test_parses_json_with_schema():
    m = _load()
    fake = _FakeCodex(_FakeThread(['{"a": 1}']))
    async def go():
        with patch.object(m, "AsyncCodex", return_value=fake):
            return await m.run_one_shot(prompt="p", model="m", system="s",
                                         schema={"required": ["a"]})
    assert asyncio.run(go()) == {"a": 1}


def test_logs_stage_on_json_success(caplog, monkeypatch):
    m = _load()
    fake = _FakeCodex(_FakeThread(['{"a": 1}']))
    monkeypatch.setenv("CODEX_STAGE_ID", "query_planner")
    caplog.set_level(logging.INFO, logger="sdk.codex.one_shot")
    async def go():
        with patch.object(m, "AsyncCodex", return_value=fake):
            return await m.run_one_shot(prompt="p", model="m", system="s",
                                         schema={"required": ["a"]})
    assert asyncio.run(go()) == {"a": 1}
    assert "stage=query_planner" in caplog.text


def test_retries_on_bad_json_then_succeeds():
    m = _load()
    fake = _FakeCodex(_FakeThread(["not json", '{"a": 1}']))
    async def go():
        with patch.object(m, "AsyncCodex", return_value=fake):
            return await m.run_one_shot(prompt="p", model="m", system="s",
                                         schema={"required": ["a"]}, max_parse_retries=1)
    assert asyncio.run(go()) == {"a": 1}


def test_raises_after_retries_exhausted():
    m = _load()
    fake = _FakeCodex(_FakeThread(["nope", "still nope"]))
    async def go():
        with patch.object(m, "AsyncCodex", return_value=fake):
            await m.run_one_shot(prompt="p", model="m", system="s",
                                  schema={"required": ["a"]}, max_parse_retries=1)
    with pytest.raises(ValueError, match="failed to parse"):
        asyncio.run(go())


def test_missing_required_field_triggers_retry():
    m = _load()
    fake = _FakeCodex(_FakeThread(['{"b": 1}', '{"a": 1, "b": 1}']))
    async def go():
        with patch.object(m, "AsyncCodex", return_value=fake):
            return await m.run_one_shot(prompt="p", model="m", system="s",
                                         schema={"required": ["a"]}, max_parse_retries=1)
    assert asyncio.run(go()) == {"a": 1, "b": 1}
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: FAIL — `run_one_shot` doesn't exist.

- [ ] **Step 3: Implement `run_one_shot` with instrumentation**

In `sdk/codex.py`, after `build_config()` (line 43) and before `async def main`, add:

```python
import asyncio as _asyncio
import json as _json
import logging as _logging
import time as _time

_LOG = _logging.getLogger("sdk.codex.one_shot")


async def run_one_shot(
    prompt: str,
    *,
    model: str,
    system: str,
    schema: dict | None = None,
    timeout: float = 120.0,
    max_parse_retries: int = 1,
) -> dict | str:
    """One input → one output via a fresh Codex thread.

    If schema is None, returns final_response as a string.
    If schema is given, parses JSON; retries up to max_parse_retries on
    parse/required-field failure, then raises ValueError.

    Logs instrumentation: stage_id (from env CODEX_STAGE_ID), model, attempts,
    wall_clock_s, input_chars, output_chars.
    """
    import os as _os
    stage_id = _os.environ.get("CODEX_STAGE_ID", "unset")
    config = build_config()
    last_err: Exception | None = None
    attempts_total = max_parse_retries + 1
    started = _time.monotonic()
    final_text = ""

    full_prompt = f"[SYSTEM]\n{system}\n\n[INPUT]\n{prompt}"
    if schema is not None:
        full_prompt += "\n\n[OUTPUT]\nReturn a single JSON object. No prose."

    async with AsyncCodex(config=config) as codex:
        thread = await codex.thread_start(model=model)
        for attempt in range(attempts_total):
            result = await _asyncio.wait_for(thread.run(full_prompt), timeout=timeout)
            final_text = result.final_response
            if schema is None:
                _LOG.info("run_one_shot ok stage=%s model=%s attempts=%d wall=%.2fs in=%d out=%d",
                          stage_id, model, attempt + 1, _time.monotonic() - started,
                          len(full_prompt), len(final_text))
                return final_text
            try:
                parsed = _json.loads(final_text)
            except _json.JSONDecodeError as exc:
                last_err = exc
                full_prompt = (
                    f"[SYSTEM]\n{system}\n\n[INPUT]\n{prompt}\n\n"
                    "[OUTPUT]\nYour previous response was not valid JSON. "
                    "Return only a JSON object. No prose."
                )
                continue
            required = schema.get("required", []) if isinstance(schema, dict) else []
            missing = [k for k in required if k not in parsed]
            if missing:
                last_err = ValueError(f"missing required fields: {missing}")
                full_prompt = (
                    f"[SYSTEM]\n{system}\n\n[INPUT]\n{prompt}\n\n"
                    f"[OUTPUT]\nYour previous response was missing required fields {missing}. "
                    "Return a JSON object with all required fields."
                )
                continue
            _LOG.info("run_one_shot ok stage=%s model=%s attempts=%d wall=%.2fs in=%d out=%d",
                      stage_id, model, attempt + 1, _time.monotonic() - started,
                      len(full_prompt), len(final_text))
            return parsed

    _LOG.error("run_one_shot failed stage=%s model=%s attempts=%d wall=%.2fs last_err=%s",
               stage_id, model, attempts_total, _time.monotonic() - started, last_err)
    raise ValueError(f"run_one_shot failed to parse after {attempts_total} attempts: {last_err}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_sdk_run_one_shot.py sdk/codex.py
git commit -m "feat(sdk): run_one_shot helper with schema validation, retry, and instrumentation"
```

---

## Task 2: Add `run_one_shot_batch`

**Files:**
- Test: extend `tests/test_sdk_run_one_shot.py`
- Modify: `sdk/codex.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk_run_one_shot.py`:

```python
def test_run_one_shot_batch_preserves_order():
    m = _load()
    async def fake_one(prompt, **_):
        return {"echo": prompt}
    async def go():
        with patch.object(m, "run_one_shot", side_effect=fake_one):
            items = [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]
            return await m.run_one_shot_batch(items, model="m", system="s",
                                               schema={"type": "object"}, concurrency=2)
    out = asyncio.run(go())
    assert [r["echo"] for r in out] == ["a", "b", "c"]


def test_run_one_shot_batch_respects_concurrency():
    m = _load()
    inflight = {"max": 0, "now": 0}
    async def fake_one(prompt, **_):
        inflight["now"] += 1
        inflight["max"] = max(inflight["max"], inflight["now"])
        await asyncio.sleep(0.05)
        inflight["now"] -= 1
        return {"echo": prompt}
    async def go():
        with patch.object(m, "run_one_shot", side_effect=fake_one):
            items = [{"prompt": str(i)} for i in range(8)]
            return await m.run_one_shot_batch(items, model="m", system="s",
                                               schema=None, concurrency=3)
    asyncio.run(go())
    assert inflight["max"] <= 3
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement `run_one_shot_batch`**

Append to `sdk/codex.py`:

```python
async def run_one_shot_batch(
    items: list[dict],
    *,
    model: str,
    system: str,
    schema: dict | None = None,
    concurrency: int = 4,
    timeout: float = 120.0,
) -> list[dict | str]:
    """Parallel one-shots. Each item must have a 'prompt' key. Order preserved."""
    sem = _asyncio.Semaphore(concurrency)

    async def _one(item: dict) -> dict | str:
        async with sem:
            return await run_one_shot(
                prompt=item["prompt"],
                model=model,
                system=system,
                schema=schema,
                timeout=timeout,
            )

    return await _asyncio.gather(*(_one(it) for it in items))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_sdk_run_one_shot.py sdk/codex.py
git commit -m "feat(sdk): run_one_shot_batch with semaphore-bounded concurrency"
```

---

## Task 3: Lift query_planner prompt into sdk_prompts/

**Files:**
- Create: `swarn_research_mcp/config/sdk_prompts/query_planner.md`

- [ ] **Step 1: Create directory and file**

```bash
mkdir -p swarn_research_mcp/config/sdk_prompts
```

Write `swarn_research_mcp/config/sdk_prompts/query_planner.md` — schema parity with `.agents/skills/query-planning/SKILL.md` is mandatory:

```markdown
Follow .agents/skills/query-planning/SKILL.md exactly.

Inputs (provided in the user message as JSON): topic (required), user_queries (optional list of strings), user_keywords (optional list of strings).

Steps:
1. Identify 4–6 distinct aspects of the topic across method families, architectural enablers, training/adaptation, evaluation, foundational priors, boundary aspects (skip axes that don't apply).
2. Per aspect emit:
   - aspect_id: short snake_case slug.
   - title: human-readable.
   - rationale: 1 sentence — why this aspect matters and what would be missed without it.
   - normal_queries: 2–3 plain-phrase queries.
   - survey_queries: 1 query starting with "survey", "review", or "overview".
   - positive_keywords: 3–5 distinctive keywords (lowercase except proper nouns / model names).
   - negative_keywords: aspect-specific exclusions (usually empty).
3. Add global_negative_keywords: 3–8 entries that exclude noise across all aspects.
4. If user_queries / user_keywords were supplied, include them verbatim in the most relevant aspect — do not drop them.

Hard rules:
- ≤ 15 normal_queries total across all aspects; ≤ 6 survey_queries total.
- No two aspects share an aspect_id, title, or > 50% of their normal_queries.
- Plain-phrase queries only (no operators / quotes).
- Never invent specific papers, methods, or numerical claims.

Return a single JSON object exactly matching this schema:

{
  "topic": "<echo of the input topic>",
  "aspects": [
    {
      "aspect_id": "sparse_attention",
      "title": "Sparse attention methods",
      "rationale": "Sparse patterns are the dominant strategy for long-context efficiency...",
      "normal_queries": ["sparse attention long context transformer", "..."],
      "survey_queries": ["survey efficient long-context attention"],
      "positive_keywords": ["sparse attention", "block-sparse", "..."],
      "negative_keywords": []
    }
  ],
  "global_negative_keywords": ["image classification only", "speech only", "graph neural network"]
}

Required top-level keys: topic, aspects, global_negative_keywords.
Required per-aspect keys: aspect_id, title, rationale, normal_queries, survey_queries, positive_keywords, negative_keywords.
```

- [ ] **Step 2: Commit**

```bash
git add swarn_research_mcp/config/sdk_prompts/query_planner.md
git commit -m "feat(sdk_prompts): query_planner prompt lifted from .toml for SDK pilot"
```

---

## Task 4: Side-by-side pilot run

**Files:**
- Create: `docs/sdk_pilot_report.md`

This task is operator-driven; record outcomes in the report file.

- [ ] **Step 1: Pick two distinct test topics**

Use small topics that exercise the planner without burning budget. Suggested:
- `"transformer attention variants"`
- `"contrastive image-text pretraining"`

- [ ] **Step 2: Run the TOML sub-agent path (baseline)**

For each topic, dispatch the `query_planner` sub-agent directly via the Codex CLI, bypassing the full orchestrator so the baseline times only this stage. Run from the repo root:

```bash
mkdir -p /tmp/sdk_pilot/baseline_t1/00_input
TIME=$(date +%s)
codex --agent query_planner --input '{"run_id": "/tmp/sdk_pilot/baseline_t1", "topic": "transformer attention variants"}' \
    > /tmp/sdk_pilot/baseline_t1.log 2>&1
END=$(date +%s)
echo "wall_clock=$((END - TIME))s"
cat /tmp/sdk_pilot/baseline_t1/00_input/search_plan.json
```

Repeat for the second topic with `baseline_t2` and `"contrastive image-text pretraining"`. Capture:
- wall-clock seconds
- aspect count from `len(search_plan["aspects"])`
- total `normal_queries` count summed across aspects

If the exact `--agent` flag in the local Codex CLI differs, run `codex --help` to find the equivalent (it may be `codex run-agent`, `codex dispatch`, etc.). Record the actual command in the report.

- [ ] **Step 3: Run the SDK path**

Save this script as `/tmp/sdk_pilot/run_sdk.py`:

```python
import asyncio, json, logging, os, sys, time
sys.path.insert(0, ".")
from sdk.codex import run_one_shot

logging.basicConfig(level=logging.INFO, format="%(message)s")
prompt_text = open("swarn_research_mcp/config/sdk_prompts/query_planner.md").read()

for tag, topic in [("sdk_t1", "transformer attention variants"),
                   ("sdk_t2", "contrastive image-text pretraining")]:
    os.environ["CODEX_STAGE_ID"] = tag
    started = time.monotonic()
    result = asyncio.run(run_one_shot(
        prompt=json.dumps({"topic": topic}),
        system=prompt_text,
        model="gpt-5.4-mini",
        schema={"required": ["topic", "aspects", "global_negative_keywords"]},
    ))
    # Per-aspect schema parity check (run_one_shot only verifies top-level required keys).
    REQUIRED_ASPECT_FIELDS = {"aspect_id", "title", "rationale", "normal_queries",
                              "survey_queries", "positive_keywords", "negative_keywords"}
    for asp in result["aspects"]:
        missing = REQUIRED_ASPECT_FIELDS - set(asp.keys())
        if missing:
            raise ValueError(f"aspect missing fields {missing}: {asp}")
    wall = time.monotonic() - started
    out_path = f"/tmp/sdk_pilot/{tag}_search_plan.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"{tag}: wall={wall:.1f}s aspects={len(result['aspects'])} "
          f"queries={sum(len(a.get('normal_queries', [])) for a in result['aspects'])} "
          f"-> {out_path}")
```

Run it from repo root:
```bash
python /tmp/sdk_pilot/run_sdk.py
```

Capture the `run_one_shot` log line for each topic — it contains `stage`, `model`, `attempts`, `wall`, `in`, `out`.

- [ ] **Step 4: Compare**

Write `docs/sdk_pilot_report.md` with sections:

```markdown
# SDK Pilot Report — query_planner

## Topics
- transformer attention variants
- contrastive image-text pretraining

## Baseline (TOML sub-agent)
| Topic | Wall-clock | Aspects | Total queries | Notes |
|---|---|---|---|---|

## SDK path (run_one_shot)
| Topic | Wall-clock | Aspects | Total queries | Notes |
|---|---|---|---|---|

## Model selection check
Did the SDK path honor `model="gpt-5.4-mini"` regardless of parent shell model? (yes/no, evidence)

## Output equivalence
Are the two search_plan outputs functionally similar (same aspect count, similar query-set IoU ≥ 0.5)?

## Decision
- Migrate query_planner now? (yes/no)
- Block on which findings?
- Next stage candidate, if go: knowledge_gap_detector or paper_ranker.
```

- [ ] **Step 5: Commit the report**

```bash
git add docs/sdk_pilot_report.md
git commit -m "docs(sdk-pilot): side-by-side report for query_planner SDK vs sub-agent"
```

---

## Task 5: Document the pilot in the orchestrator SKILL

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`

- [ ] **Step 1: Add a small pilot note**

Append a section near the bottom:

```markdown
## SDK pilot (query_planner only — pilot, not yet load-bearing)
A pilot exists at `swarn_research_mcp/config/sdk_prompts/query_planner.md` running through `sdk.codex.run_one_shot`. It is invoked manually via the test harness; the orchestrator still uses `.codex/agents/query_planner.toml` as the production path. After `docs/sdk_pilot_report.md` records a "go" decision, a follow-up plan will:
- Switch stage 1 to the SDK path.
- Delete `.codex/agents/query_planner.toml`.
- Consider knowledge_gap_detector and paper_ranker for the next migration.
Stages that read multiple files (outline_planner, chapter_manifest_builder) are explicitly NOT migration candidates.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "docs(orchestrator): note query_planner SDK pilot, defer migration to follow-up plan"
```

---

# Self-Review

**Spec coverage (§7 only):**
- `run_one_shot` helper → Task 1
- `run_one_shot_batch` helper → Task 2
- Single-stage pilot (`query_planner`) → Task 3 (prompt), Task 4 (run), Task 5 (docs)
- Instrumentation for context-relief and model-honoring evidence → built into `run_one_shot` in Task 1; recorded in Task 4

**Out of scope (intentional):**
- `outline_planner` and `chapter_manifest_builder` — removed because both read multiple files and edit chapter files in place; they fail the "single JSON in, single JSON out" rule.
- TOML deletions — defer to a follow-up plan after the pilot's go/no-go decision.

**Type consistency:**
- `run_one_shot` and `run_one_shot_batch` signatures match across Task 1 / Task 2 / Task 4
- Prompt file path is stable: `swarn_research_mcp/config/sdk_prompts/query_planner.md`

**Decision gates:**
- Task 4 produces `docs/sdk_pilot_report.md` with an explicit Decision section. No further migration begins until a "go" is recorded there.
