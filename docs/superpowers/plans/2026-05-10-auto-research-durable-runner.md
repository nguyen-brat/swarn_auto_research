# Auto Research Durable Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable, resumable Python control plane so the auto-research pipeline can run end-to-end without depending on one long interactive Codex session staying alive.

**Architecture:** `scripts/run_auto_research.py` becomes the durable orchestrator. It owns run state, shard manifests, artifact checks, retries, and deterministic stage merges. Codex agents still do the language-model work through `codex exec`; the runner decides completion from files, not from a parent model's context or a single `wait_agent` return.

**Tech Stack:** Python 3.11, pytest, subprocess, JSON/CSV file manifests, existing `.codex/agents/*.toml`, existing `.agents/skills/*`, existing `swarn_research_mcp.research_book` deterministic generators/validators.

---

## Problem Being Fixed

The latest stopped run, `research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939`, reached Stage 11 and spawned all verified-graph shards. The parent session called `wait_agent` with multiple targets, got one completed shard, returned a final answer, and stopped. The remaining shards finished afterward, but the parent never merged `11_verified_graph/fragments/*.json` into `11_verified_graph/global_graph.json` and never ran Stages 12-18.

The fix is not "better prompt wording." The fix is a durable runner that:

- records expected shards before dispatch;
- checks expected artifact files after dispatch;
- keeps waiting or reruns only missing shards;
- runs deterministic merges after all outputs exist;
- can be restarted and resume from the first incomplete artifact.

## Non-Goals

- Do not delete `.codex/agents/*.toml`.
- Do not replace taxonomy, chapter packs, chapter prose, verification, or manifest/front-matter edits with parent-authored templates.
- Do not make the SDK pilot (`2026-05-10-codex-sdk-context-relief-pilot.md`) a prerequisite. SDK one-shot stages can be adopted later.
- Do not try to finish a real research run inside unit tests.

## File Map

**Create:**
- `scripts/run_auto_research.py` — durable CLI runner and stage control plane.
- `tests/test_auto_research_runner_state.py` — run state, logging, artifact checks.
- `tests/test_auto_research_runner_stage11.py` — verified graph merge/resume regression.
- `tests/test_auto_research_runner_dispatch.py` — subprocess dispatch, shard manifests, all-shards-complete behavior.
- `tests/test_auto_research_runner_cli.py` — CLI argument handling and resume behavior.

**Modify:**
- `.agents/skills/auto-research-orchestrator/SKILL.md` — mark the Python runner as the preferred end-to-end path; keep the skill as the stage contract.
- `docs/superpowers/plans/2026-05-10-auto-research-implementation-roadmap.md` — add this runner plan as the next required reliability shard before more full-system pilots.

**Optional follow-up, not in this plan:**
- Implement `sdk/codex.py::run_one_shot` from `2026-05-10-codex-sdk-context-relief-pilot.md` and migrate only small JSON stages after this runner is stable.

---

## Runner Contract

### CLI

```bash
python scripts/run_auto_research.py --topic "Advanced LLM architecture for latent reasoning using recurrent / looped Transformers" --phase draft
python scripts/run_auto_research.py --run-id advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939 --phase all --resume --from-stage 11
python scripts/run_auto_research.py --run-id advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939 --phase write --resume
```

### State Files

The runner writes under each run:

```text
run_control/
  run_state.json
  stages/
    11/
      stage.json
      shards/
        vgraph-01.json
        vgraph-02.json
```

`run_control/run_state.json` schema:

```json
{
  "run_id": "advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939",
  "phase": "all",
  "topic": "Advanced LLM architecture for latent reasoning using recurrent / looped Transformers",
  "status": "running",
  "current_stage": "11",
  "last_completed_stage": "10",
  "created_at": "2026-05-10T16:49:39+07:00",
  "updated_at": "2026-05-10T19:43:51+07:00"
}
```

Shard manifest schema:

```json
{
  "stage": "11",
  "shard_id": "vgraph-02",
  "agent": "verified_graph_extractor",
  "model": "gpt-5.4-mini",
  "attempt": 1,
  "items": ["2510.04182", "2601.21582"],
  "expected_outputs": [
    "11_verified_graph/fragments/2510.04182.json",
    "11_verified_graph/fragments/2601.21582.json"
  ],
  "status": "completed",
  "started_at": "2026-05-10T19:38:41+07:00",
  "finished_at": "2026-05-10T19:43:51+07:00",
  "returncode": 0,
  "stdout_path": "run_control/stages/11/shards/vgraph-02.stdout.txt",
  "stderr_path": "run_control/stages/11/shards/vgraph-02.stderr.txt"
}
```

### Completion Rule

A stage is complete only when its primary artifact contract is true. For sharded stages, a subprocess exit code is not sufficient. Every expected output file must exist and pass the stage-specific validation.

---

# Task 1: Runner State, Logging, and Artifact Utilities

**Files:**
- Create: `scripts/run_auto_research.py`
- Create: `tests/test_auto_research_runner_state.py`

- [ ] **Step 1: Write failing tests for state and logs**

Create `tests/test_auto_research_runner_state.py`:

```python
from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.run_auto_research import (
    append_run_log,
    ensure_run_control,
    load_run_state,
    primary_artifact_exists,
    save_run_state,
)


def test_save_and_load_run_state(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    ensure_run_control(run)

    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "all",
            "topic": "Demo topic",
            "status": "running",
            "current_stage": "11",
            "last_completed_stage": "10",
        },
    )

    state = load_run_state(run)
    assert state["run_id"] == "demo"
    assert state["current_stage"] == "11"
    assert state["last_completed_stage"] == "10"
    assert "updated_at" in state


def test_append_run_log_creates_header_and_rows(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)

    append_run_log(run, "11", "merged", "59 fragments -> global_graph.json")
    append_run_log(run, "12", "started", "outline_planner")

    with (run / "run_log.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["stage"] == "11"
    assert rows[0]["status"] == "merged"
    assert rows[1]["stage"] == "12"
    assert rows[1]["detail"] == "outline_planner"


def test_primary_artifact_exists_for_stage_11(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    (run / "11_verified_graph").mkdir(parents=True)
    assert primary_artifact_exists(run, "11") is False

    (run / "11_verified_graph" / "global_graph.json").write_text(
        json.dumps({"nodes": [], "edges": []})
    )
    assert primary_artifact_exists(run, "11") is True
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_state.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing functions.

- [ ] **Step 3: Implement minimal state/log/artifact utilities**

Create `scripts/run_auto_research.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "research_runs"

PRIMARY_ARTIFACTS = {
    "0": ["run_config.json"],
    "1": ["00_input/search_plan.json", "02_paper_pool/paper_pool.json"],
    "3": ["05_weak_graph/weak_global_graph.json"],
    "4": ["06_expansion/known_concepts_snapshot.json"],
    "5": ["06_expansion/knowledge_gap_report.json", "06_expansion/expansion_need_queue.json"],
    "6": ["06_expansion/expansion_round_01.json"],
    "7": ["07_scoring/promoted_papers.json"],
    "11": ["11_verified_graph/global_graph.json", "11_verified_graph/graph_report.md"],
    "12": ["12_taxonomy/outline.json"],
    "15": ["15_verification/verification_summary.csv"],
    "16": ["16_book/chapters_manifest.json"],
    "17": ["17_learning_suggestions/knowledge_to_add.md"],
    "18": ["16_book/SUMMARY.md", "16_book/sidebar.json", "16_book/appendices/references.md"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_run_control(run_dir: Path) -> Path:
    control = run_dir / "run_control"
    (control / "stages").mkdir(parents=True, exist_ok=True)
    return control


def load_run_state(run_dir: Path) -> dict[str, Any]:
    path = ensure_run_control(run_dir) / "run_state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_run_state(run_dir: Path, state: dict[str, Any]) -> None:
    path = ensure_run_control(run_dir) / "run_state.json"
    next_state = dict(state)
    next_state["updated_at"] = now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(next_state, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def append_run_log(run_dir: Path, stage: str, status: str, detail: str) -> None:
    path = run_dir / "run_log.csv"
    exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "stage", "status", "detail"])
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": now_iso(),
            "stage": stage,
            "status": status,
            "detail": detail,
        })


def primary_artifact_exists(run_dir: Path, stage: str) -> bool:
    rels = PRIMARY_ARTIFACTS.get(str(stage), [])
    return bool(rels) and all((run_dir / rel).exists() for rel in rels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Durable auto-research pipeline runner")
    parser.add_argument("--topic")
    parser.add_argument("--run-id")
    parser.add_argument("--phase", choices=["draft", "write", "all"], default="all")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--from-stage", default=None)
    args = parser.parse_args(argv)

    if not args.topic and not args.run_id:
        parser.error("one of --topic or --run-id is required")

    run_id = args.run_id or "pending-topic-run"
    run_dir = RUNS_ROOT / run_id
    ensure_run_control(run_dir)
    state = load_run_state(run_dir)
    state.update({
        "run_id": run_id,
        "phase": args.phase,
        "topic": args.topic or state.get("topic", ""),
        "status": "ready",
        "current_stage": args.from_stage or state.get("current_stage", "0"),
    })
    save_run_state(run_dir, state)
    print(f"runner ready: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_state.py
git commit -m "feat(auto-research): add durable runner state primitives"
```

---

# Task 2: Stage 11 Verified Graph Merge and Resume Regression

This task fixes the exact observed failure mode: all `11_verified_graph/fragments/*.json` exist, but `global_graph.json` and `graph_report.md` do not.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Create: `tests/test_auto_research_runner_stage11.py`

- [ ] **Step 1: Write failing Stage 11 merge tests**

Create `tests/test_auto_research_runner_stage11.py`:

```python
from __future__ import annotations

import json

from scripts.run_auto_research import merge_verified_graph_fragments, run_stage_11_merge


def _write_fragment(run, arxiv_id, nodes, edges):
    path = run / "11_verified_graph" / "fragments" / f"{arxiv_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"arxiv_id": arxiv_id, "nodes": nodes, "edges": edges}))


def test_merge_verified_graph_fragments_dedupes_nodes_and_edges(tmp_path):
    run = tmp_path / "run"
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "looped-transformer", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "looped-transformer",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.1",
            "source_lines": [1, 2],
        }],
    )
    _write_fragment(
        run,
        "1.2",
        [{"id": "1.2", "type": "Paper"}, {"id": "looped-transformer", "type": "Method"}],
        [{
            "src": "1.2",
            "dst": "looped-transformer",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.2",
            "source_lines": [3, 4],
        }],
    )

    graph = merge_verified_graph_fragments(run)

    assert {n["id"] for n in graph["nodes"]} == {"1.1", "1.2", "looped-transformer"}
    assert len(graph["edges"]) == 2
    assert all(e["confidence"] == "verified" for e in graph["edges"])
    assert all(e["source_node_id"] for e in graph["edges"])


def test_run_stage_11_merge_writes_global_graph_report_and_log(tmp_path):
    run = tmp_path / "run"
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "m", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "m",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.1",
            "source_lines": [1],
        }],
    )
    (run / "05_weak_graph").mkdir(parents=True)
    (run / "05_weak_graph" / "weak_global_graph.json").write_text(
        json.dumps({"nodes": [], "edges": [{"src": "x", "dst": "y", "type": "USES"}]})
    )

    run_stage_11_merge(run)

    global_graph = run / "11_verified_graph" / "global_graph.json"
    report = run / "11_verified_graph" / "graph_report.md"
    assert global_graph.exists()
    assert report.exists()
    assert "Verified graph report" in report.read_text()
    assert "11,merged" in (run / "run_log.csv").read_text()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_stage11.py -v
```

Expected: FAIL because Stage 11 functions do not exist.

- [ ] **Step 3: Implement Stage 11 merge**

Append these functions to `scripts/run_auto_research.py` before `main()`:

```python
def _edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        edge.get("src"),
        edge.get("dst"),
        edge.get("type"),
        edge.get("source_node_id"),
        tuple(edge.get("source_lines") or []),
    )


def merge_verified_graph_fragments(run_dir: Path) -> dict[str, Any]:
    fragments_dir = run_dir / "11_verified_graph" / "fragments"
    if not fragments_dir.exists():
        raise FileNotFoundError(f"missing Stage 11 fragments directory: {fragments_dir}")

    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for path in sorted(fragments_dir.glob("*.json")):
        data = json.loads(path.read_text())
        for node in data.get("nodes", []):
            node_id = node.get("id")
            if node_id:
                nodes_by_id.setdefault(node_id, node)
        for edge in data.get("edges", []):
            if edge.get("confidence") != "verified":
                raise ValueError(f"{path} has non-verified edge: {edge}")
            if not edge.get("source_node_id"):
                raise ValueError(f"{path} has edge without source_node_id: {edge}")
            if not edge.get("source_lines"):
                raise ValueError(f"{path} has edge without source_lines: {edge}")
            edges_by_key.setdefault(_edge_key(edge), edge)

    return {
        "nodes": [nodes_by_id[k] for k in sorted(nodes_by_id)],
        "edges": [edges_by_key[k] for k in sorted(edges_by_key)],
    }


def _load_weak_edge_count(run_dir: Path) -> int:
    path = run_dir / "05_weak_graph" / "weak_global_graph.json"
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    return len(data.get("edges", []))


def run_stage_11_merge(run_dir: Path) -> None:
    graph = merge_verified_graph_fragments(run_dir)
    out_dir = run_dir / "11_verified_graph"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "global_graph.json").write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n")

    weak_edges = _load_weak_edge_count(run_dir)
    verified_edges = len(graph["edges"])
    dropped = max(weak_edges - verified_edges, 0)
    report = "\n".join([
        "# Verified graph report",
        "",
        f"- Nodes: {len(graph['nodes'])}",
        f"- Verified edges: {verified_edges}",
        f"- Weak edges not promoted: {dropped}",
        "",
    ])
    (out_dir / "graph_report.md").write_text(report)
    append_run_log(run_dir, "11", "merged", f"{verified_edges} verified edges")
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_stage11.py tests/test_auto_research_runner_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Verify against the interrupted real run without changing earlier stages**

Run:

```bash
env PYTHONPATH=. python -c "from pathlib import Path; from scripts.run_auto_research import run_stage_11_merge; run_stage_11_merge(Path('research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939'))"
test -f research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939/11_verified_graph/global_graph.json
test -f research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939/11_verified_graph/graph_report.md
```

Expected: both `test -f` commands exit 0.

If this verification mutates the real interrupted run, do not commit those `research_runs/` artifacts. They are runtime output.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_stage11.py
git commit -m "feat(auto-research): add durable Stage 11 merge"
```

---

# Task 3: Codex Worker Dispatch Adapter with Shard Manifests

This adds subprocess dispatch without relying on `wait_agent`. The runner launches `codex exec` processes, records expected outputs, then validates files.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Create: `tests/test_auto_research_runner_dispatch.py`

- [ ] **Step 1: Write failing dispatch tests**

Create `tests/test_auto_research_runner_dispatch.py`:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.run_auto_research import ShardSpec, expected_outputs_exist, run_shards


def test_expected_outputs_exist_requires_every_file(tmp_path):
    run = tmp_path / "run"
    spec = ShardSpec(
        stage="11",
        shard_id="vgraph-01",
        agent="verified_graph_extractor",
        model="gpt-5.4-mini",
        prompt="p",
        expected_outputs=["11_verified_graph/fragments/1.json", "11_verified_graph/fragments/2.json"],
    )
    (run / "11_verified_graph" / "fragments").mkdir(parents=True)
    (run / "11_verified_graph" / "fragments" / "1.json").write_text("{}")

    assert expected_outputs_exist(run, spec) is False

    (run / "11_verified_graph" / "fragments" / "2.json").write_text("{}")
    assert expected_outputs_exist(run, spec) is True


def test_run_shards_records_manifest_and_retries_missing_output(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    spec = ShardSpec(
        stage="11",
        shard_id="vgraph-01",
        agent="verified_graph_extractor",
        model="gpt-5.4-mini",
        prompt="write the fragment",
        expected_outputs=["11_verified_graph/fragments/1.json"],
    )
    calls = {"count": 0}

    def fake_run(cmd, cwd, text, stdout, stderr):
        calls["count"] += 1
        if calls["count"] == 2:
            out = run / "11_verified_graph" / "fragments" / "1.json"
            out.parent.mkdir(parents=True)
            out.write_text(json.dumps({"nodes": [], "edges": []}))
        return subprocess.CompletedProcess(cmd, 0)

    with patch("scripts.run_auto_research.subprocess.run", side_effect=fake_run):
        run_shards(run, [spec], max_retries=1)

    manifest = run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["status"] == "completed"
    assert data["attempt"] == 2
    assert calls["count"] == 2
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_dispatch.py -v
```

Expected: FAIL because dispatch functions do not exist.

- [ ] **Step 3: Implement dispatch adapter**

Add after imports in `scripts/run_auto_research.py`:

```python
@dataclass
class ShardSpec:
    stage: str
    shard_id: str
    agent: str
    model: str
    prompt: str
    expected_outputs: list[str]
```

Add before `main()`:

```python
def expected_outputs_exist(run_dir: Path, spec: ShardSpec) -> bool:
    return all((run_dir / rel).exists() for rel in spec.expected_outputs)


def _shard_dir(run_dir: Path, spec: ShardSpec) -> Path:
    path = ensure_run_control(run_dir) / "stages" / spec.stage / "shards"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_shard_manifest(
    run_dir: Path,
    spec: ShardSpec,
    *,
    attempt: int,
    status: str,
    returncode: int | None,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    path = _shard_dir(run_dir, spec) / f"{spec.shard_id}.json"
    payload = {
        "stage": spec.stage,
        "shard_id": spec.shard_id,
        "agent": spec.agent,
        "model": spec.model,
        "attempt": attempt,
        "expected_outputs": spec.expected_outputs,
        "status": status,
        "returncode": returncode,
        "stdout_path": str(stdout_path.relative_to(run_dir)),
        "stderr_path": str(stderr_path.relative_to(run_dir)),
        "updated_at": now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _codex_exec_command(spec: ShardSpec) -> list[str]:
    return [
        "codex",
        "exec",
        "--cd",
        str(REPO_ROOT),
        "--model",
        spec.model,
        "--ask-for-approval",
        "never",
        spec.prompt,
    ]


def run_shards(run_dir: Path, specs: list[ShardSpec], *, max_retries: int = 1) -> None:
    for spec in specs:
        if expected_outputs_exist(run_dir, spec):
            continue
        for attempt in range(1, max_retries + 2):
            shard_dir = _shard_dir(run_dir, spec)
            stdout_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
            stderr_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
            with stdout_path.open("w") as out, stderr_path.open("w") as err:
                completed = subprocess.run(
                    _codex_exec_command(spec),
                    cwd=REPO_ROOT,
                    text=True,
                    stdout=out,
                    stderr=err,
                )
            status = "completed" if completed.returncode == 0 and expected_outputs_exist(run_dir, spec) else "failed"
            _write_shard_manifest(
                run_dir,
                spec,
                attempt=attempt,
                status=status,
                returncode=completed.returncode,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            if status == "completed":
                break
        if not expected_outputs_exist(run_dir, spec):
            append_run_log(run_dir, spec.stage, "failed", f"{spec.shard_id} missing expected outputs")
            raise RuntimeError(f"Shard {spec.stage}/{spec.shard_id} did not produce expected outputs")
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_dispatch.py tests/test_auto_research_runner_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_dispatch.py
git commit -m "feat(auto-research): add durable Codex shard dispatch"
```

---

# Task 4: Stage 11 Resume Handler

This wires artifact checks, missing-fragment dispatch, and merge into one stage handler. It is the smallest end-to-end proof that the runner fixes the latest stop.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_stage11.py`

- [ ] **Step 1: Add failing tests for Stage 11 resume**

Append to `tests/test_auto_research_runner_stage11.py`:

```python
from unittest.mock import patch

from scripts.run_auto_research import run_stage_11


def test_run_stage_11_merges_when_all_fragments_already_exist(tmp_path):
    run = tmp_path / "run"
    (run / "07_scoring").mkdir(parents=True)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": "1.1"}]})
    )
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "m", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "m",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.1",
            "source_lines": [1],
        }],
    )

    with patch("scripts.run_auto_research.run_shards") as run_shards:
        run_stage_11(run)

    run_shards.assert_not_called()
    assert (run / "11_verified_graph" / "global_graph.json").exists()


def test_run_stage_11_dispatches_only_missing_fragments(tmp_path):
    run = tmp_path / "run"
    (run / "07_scoring").mkdir(parents=True)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": "1.1"}, {"arxiv_id": "1.2"}]})
    )
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}],
        [{
            "src": "1.1",
            "dst": "1.1",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.1",
            "source_lines": [1],
        }],
    )

    def fake_run_shards(run_dir, specs, max_retries=1):
        assert len(specs) == 1
        assert specs[0].shard_id == "vgraph-resume-001"
        assert specs[0].expected_outputs == ["11_verified_graph/fragments/1.2.json"]
        _write_fragment(
            run_dir,
            "1.2",
            [{"id": "1.2", "type": "Paper"}],
            [{
                "src": "1.2",
                "dst": "1.2",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.2",
                "source_lines": [2],
            }],
        )

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert (run / "11_verified_graph" / "global_graph.json").exists()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_stage11.py -v
```

Expected: FAIL because `run_stage_11` does not exist.

- [ ] **Step 3: Implement Stage 11 handler**

Add before `main()`:

```python
def load_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    path = run_dir / "07_scoring" / "promoted_papers.json"
    data = json.loads(path.read_text())
    return [str(item["arxiv_id"]) for item in data.get("promoted_papers", [])]


def _stage_11_prompt(run_id: str, shard_id: str, arxiv_ids: list[str]) -> str:
    return "\n".join([
        "Read AGENTS.md first.",
        "Run Stage 11 verified graph extraction only.",
        f"run_id={run_id}",
        f"shard_id={shard_id}",
        f"arxiv_ids={arxiv_ids}",
        "Follow .codex/agents/verified_graph_extractor.toml and .agents/skills/verified-graph-extraction/SKILL.md.",
        "Read 10_verified_evidence and 05_weak_graph/fragments for these ids.",
        "Write only 11_verified_graph/fragments/{arxiv_id}.json.",
        "Do not write 11_verified_graph/global_graph.json.",
        "Return the standard short success string.",
    ])


def run_stage_11(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "11"):
        append_run_log(run_dir, "11", "skipped", "global graph already present")
        return

    run_id = run_dir.name
    promoted = load_promoted_arxiv_ids(run_dir)
    missing = [
        aid for aid in promoted
        if not (run_dir / "11_verified_graph" / "fragments" / f"{aid}.json").exists()
    ]
    specs = [
        ShardSpec(
            stage="11",
            shard_id=f"vgraph-resume-{idx:03d}",
            agent="verified_graph_extractor",
            model="gpt-5.4-mini",
            prompt=_stage_11_prompt(run_id, f"vgraph-resume-{idx:03d}", [aid]),
            expected_outputs=[f"11_verified_graph/fragments/{aid}.json"],
        )
        for idx, aid in enumerate(missing, start=1)
    ]
    if specs:
        append_run_log(run_dir, "11", "dispatching", f"{len(specs)} missing fragments")
        run_shards(run_dir, specs)

    still_missing = [
        aid for aid in promoted
        if not (run_dir / "11_verified_graph" / "fragments" / f"{aid}.json").exists()
    ]
    if still_missing:
        raise RuntimeError(f"Stage 11 still missing fragments: {still_missing}")
    run_stage_11_merge(run_dir)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_stage11.py tests/test_auto_research_runner_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 5: Verify on the interrupted run**

Run:

```bash
env PYTHONPATH=. python -c "from pathlib import Path; from scripts.run_auto_research import run_stage_11; run_stage_11(Path('research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939'))"
test -f research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939/11_verified_graph/global_graph.json
```

Expected: exits 0. The runner should dispatch no workers because all 59 fragments are already present.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_stage11.py
git commit -m "feat(auto-research): resume and close Stage 11"
```

---

# Task 5: Deterministic Stage Closers for 12.5, 15, 16, and 18

This task adds deterministic closers the runner can safely execute without asking a model to remember state.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Create: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Write failing closer tests**

Create `tests/test_auto_research_runner_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.run_auto_research import run_deterministic_command, run_stage_18


def test_run_deterministic_command_logs_failure(tmp_path):
    run = tmp_path / "run"
    run.mkdir()

    with patch("scripts.run_auto_research.subprocess.run") as mocked:
        mocked.return_value.returncode = 7
        mocked.return_value.stdout = "out"
        mocked.return_value.stderr = "bad"
        try:
            run_deterministic_command(run, "18", ["python", "-m", "bad"])
        except RuntimeError as exc:
            assert "stage 18 command failed" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")

    assert "18,failed" in (run / "run_log.csv").read_text()


def test_run_stage_18_runs_generate_then_validate(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    calls = []

    def fake_command(run_dir, stage, cmd):
        calls.append(cmd)
        if "--generate" in cmd:
            (run / "16_book").mkdir(exist_ok=True)
            (run / "16_book" / "SUMMARY.md").write_text("# Summary\n")
            (run / "16_book" / "sidebar.json").write_text("{}")
            (run / "16_book" / "appendices").mkdir(exist_ok=True)
            (run / "16_book" / "appendices" / "references.md").write_text("# References\n")

    with patch("scripts.run_auto_research.run_deterministic_command", side_effect=fake_command):
        run_stage_18(run)

    assert calls[0][-1] == "--generate"
    assert calls[1][-1] == "--validate"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
```

Expected: FAIL because closer functions do not exist.

- [ ] **Step 3: Implement deterministic command helpers and Stage 18**

Add before `main()`:

```python
def run_deterministic_command(run_dir: Path, stage: str, cmd: list[str]) -> None:
    completed = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    detail = " ".join(cmd)
    if completed.returncode != 0:
        append_run_log(run_dir, stage, "failed", detail)
        control = ensure_run_control(run_dir) / "stages" / stage
        control.mkdir(parents=True, exist_ok=True)
        (control / "last_stdout.txt").write_text(completed.stdout or "")
        (control / "last_stderr.txt").write_text(completed.stderr or "")
        raise RuntimeError(f"stage {stage} command failed: {detail}")
    append_run_log(run_dir, stage, "completed", detail)


def run_stage_12_5(run_dir: Path) -> None:
    run_deterministic_command(
        run_dir,
        "12.5",
        [sys.executable, "-m", "swarn_research_mcp.research_book", str(run_dir), "--normalize-outline"],
    )


def run_stage_18(run_dir: Path) -> None:
    run_deterministic_command(
        run_dir,
        "18",
        [sys.executable, "-m", "swarn_research_mcp.research_book", str(run_dir), "--generate"],
    )
    run_deterministic_command(
        run_dir,
        "18",
        [sys.executable, "-m", "swarn_research_mcp.research_book", str(run_dir), "--validate"],
    )
    if not primary_artifact_exists(run_dir, "18"):
        raise RuntimeError("Stage 18 did not produce book artifacts")
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py tests/test_auto_research_runner_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat(auto-research): add deterministic runner stage closers"
```

---

# Task 6: Stage Handlers for 12, 13, 14, 15, 16, and 17

This task wires Codex worker prompts for the remaining model-driven stages. The handlers are intentionally thin: they build expected outputs, dispatch missing shards, then validate artifacts.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Add target-building tests**

Append to `tests/test_auto_research_runner_cli.py`:

```python
from scripts.run_auto_research import build_chapter_targets


def test_build_chapter_targets_excludes_appendices_and_keeps_order(tmp_path):
    run = tmp_path / "run"
    (run / "12_taxonomy").mkdir(parents=True)
    outline = {
        "book_sections": [
            {"id": "preface", "title": "Preface"},
            {"id": "appendices", "title": "Appendices"},
        ],
        "families": [{"id": "fam_a", "title": "A", "method_ids": ["m1"]}],
        "methods": [{"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"}],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))

    targets = build_chapter_targets(run)

    assert targets == [
        {"type": "book", "id": "preface"},
        {"type": "families", "id": "fam_a"},
        {"type": "methods", "id": "m1"},
    ]
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_build_chapter_targets_excludes_appendices_and_keeps_order -v
```

Expected: FAIL because `build_chapter_targets` does not exist.

- [ ] **Step 3: Implement target builders and stage prompts**

Add before `main()`:

```python
def load_outline(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())


def build_chapter_targets(run_dir: Path) -> list[dict[str, str]]:
    outline = load_outline(run_dir)
    targets: list[dict[str, str]] = []
    for section in outline.get("book_sections", []):
        if section["id"] == "appendices":
            continue
        targets.append({"type": "book", "id": section["id"]})
    for family in outline.get("families", []):
        if family.get("is_group") or family["id"] == "standalone":
            continue
        targets.append({"type": "families", "id": family["id"]})
    for method in outline.get("methods", []):
        targets.append({"type": "methods", "id": method["id"]})
    return targets


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _generic_agent_prompt(agent_toml: str, run_id: str, stage: str, shard_id: str, payload: dict[str, Any]) -> str:
    return "\n".join([
        "Read AGENTS.md first.",
        f"Run Stage {stage} only.",
        f"run_id={run_id}",
        f"shard_id={shard_id}",
        f"payload={json.dumps(payload, sort_keys=True)}",
        f"Follow {agent_toml} exactly.",
        "Write only the artifacts required by that agent and shard.",
        "Return the standard short success string.",
    ])
```

- [ ] **Step 4: Implement Stage 12 outline handler**

Add:

```python
def run_stage_12(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "12"):
        append_run_log(run_dir, "12", "skipped", "outline already present")
        return
    spec = ShardSpec(
        stage="12",
        shard_id="outline",
        agent="outline_planner",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/outline_planner.toml",
            run_dir.name,
            "12",
            "outline",
            {"expected_outputs": ["12_taxonomy/communities.json", "12_taxonomy/taxonomy.json", "12_taxonomy/outline.json"]},
        ),
        expected_outputs=[
            "12_taxonomy/communities.json",
            "12_taxonomy/taxonomy.json",
            "12_taxonomy/outline.json",
        ],
    )
    run_shards(run_dir, [spec])
```

- [ ] **Step 5: Implement Stages 13-16 thin handlers**

Add:

```python
def _expected_chapter_pack(target: dict[str, str]) -> str:
    return f"13_chapter_packs/{target['type']}/{target['id']}.json"


def _expected_chapter_file(target: dict[str, str]) -> str:
    suffix = ".md"
    return f"14_chapters/{target['type']}/{target['id']}{suffix}"


def _expected_verification_file(target: dict[str, str]) -> str:
    return f"15_verification/{target['type']}/{target['id']}_verification.json"


def run_stage_13(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    missing = [t for t in targets if not (run_dir / _expected_chapter_pack(t)).exists()]
    specs = [
        ShardSpec(
            stage="13",
            shard_id=f"pack-{idx:03d}",
            agent="chapter_pack_builder",
            model="gpt-5.4-mini",
            prompt=_generic_agent_prompt(".codex/agents/chapter_pack_builder.toml", run_dir.name, "13", f"pack-{idx:03d}", {"targets": chunk}),
            expected_outputs=[_expected_chapter_pack(t) for t in chunk],
        )
        for idx, chunk in enumerate(chunked(missing, 1), start=1)
    ]
    if specs:
        run_shards(run_dir, specs)


def run_stage_14(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    missing = [t for t in targets if not (run_dir / _expected_chapter_file(t)).exists()]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 2), start=1):
        types = {t["type"] for t in chunk}
        agent = "method_chapter_writer" if types == {"methods"} else "family_chapter_writer" if types == {"families"} else "book_section_writer"
        specs.append(ShardSpec(
            stage="14",
            shard_id=f"write-{idx:03d}",
            agent=agent,
            model="gpt-5.4",
            prompt=_generic_agent_prompt(f".codex/agents/{agent}.toml", run_dir.name, "14", f"write-{idx:03d}", {"targets": chunk}),
            expected_outputs=[_expected_chapter_file(t) for t in chunk],
        ))
    if specs:
        run_shards(run_dir, specs)


def run_stage_15(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    missing = [t for t in targets if not (run_dir / _expected_verification_file(t)).exists()]
    specs = [
        ShardSpec(
            stage="15",
            shard_id=f"verify-{idx:03d}",
            agent="verifier",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(".codex/agents/verifier.toml", run_dir.name, "15", f"verify-{idx:03d}", {"targets": chunk}),
            expected_outputs=[_expected_verification_file(t) for t in chunk],
        )
        for idx, chunk in enumerate(chunked(missing, 2), start=1)
    ]
    if specs:
        run_shards(run_dir, specs)


def run_stage_16(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    specs = [
        ShardSpec(
            stage="16",
            shard_id=f"manifest-{idx:03d}",
            agent="chapter_manifest_builder",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(".codex/agents/chapter_manifest_builder.toml", run_dir.name, "16", f"manifest-{idx:03d}", {"targets": chunk}),
            expected_outputs=[f"16_book/chapters_manifest_shard_manifest-{idx:03d}.json"],
        )
        for idx, chunk in enumerate(chunked(targets, 2), start=1)
        if not (run_dir / f"16_book/chapters_manifest_shard_manifest-{idx:03d}.json").exists()
    ]
    if specs:
        run_shards(run_dir, specs)
```

- [ ] **Step 6: Add Stage 17 handler**

Add:

```python
def run_stage_17(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "17"):
        append_run_log(run_dir, "17", "skipped", "learning suggestions already present")
        return
    spec = ShardSpec(
        stage="17",
        shard_id="learning-suggestions",
        agent="knowledge_gap_detector",
        model="gpt-5.4-mini",
        prompt="\n".join([
            "Read AGENTS.md first.",
            "Run Stage 17 learning suggestions only.",
            f"run_id={run_dir.name}",
            "Read 06_expansion/knowledge_gap_report.json.",
            "Write 17_learning_suggestions/knowledge_to_add.md.",
            "Do not modify .agents/knowledge_base.md.",
        ]),
        expected_outputs=["17_learning_suggestions/knowledge_to_add.md"],
    )
    run_shards(run_dir, [spec])
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py tests/test_auto_research_runner_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat(auto-research): add durable handlers for late stages"
```

---

# Task 7: CLI Stage Loop and Resume

This task makes the CLI run stages in order, skip completed artifacts, and resume from `--from-stage`.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Add failing CLI resume test**

Append to `tests/test_auto_research_runner_cli.py`:

```python
from scripts.run_auto_research import main


def test_main_resume_from_stage_11_calls_stage_11(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    calls = []

    def fake_stage(run_dir):
        calls.append(run_dir.name)

    monkeypatch.setattr("scripts.run_auto_research.run_stage_11", fake_stage)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_13", lambda run_dir: None)

    rc = main(["--run-id", "demo", "--phase", "draft", "--resume", "--from-stage", "11"])

    assert rc == 0
    assert calls == ["demo"]
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_main_resume_from_stage_11_calls_stage_11 -v
```

Expected: FAIL because `main()` only writes state.

- [ ] **Step 3: Implement stage loop**

Replace the body of `main()` after argument parsing with:

```python
    if not args.topic and not args.run_id:
        parser.error("one of --topic or --run-id is required")

    run_id = args.run_id
    if run_id is None:
        parser.error("new-run creation is not implemented until Task 8; pass --run-id for now")
    run_dir = RUNS_ROOT / run_id
    if not run_dir.exists():
        parser.error(f"run directory does not exist: {run_dir}")

    state = load_run_state(run_dir)
    state.update({
        "run_id": run_id,
        "phase": args.phase,
        "topic": args.topic or state.get("topic", ""),
        "status": "running",
        "current_stage": args.from_stage or state.get("current_stage", "11"),
    })
    save_run_state(run_dir, state)

    handlers = [
        ("11", run_stage_11),
        ("12", run_stage_12),
        ("12.5", run_stage_12_5),
        ("13", run_stage_13),
    ]
    if args.phase in {"write", "all"}:
        handlers.extend([
            ("14", run_stage_14),
            ("15", run_stage_15),
            ("16", run_stage_16),
            ("17", run_stage_17),
            ("18", run_stage_18),
        ])
    if args.phase == "draft":
        handlers = [h for h in handlers if h[0] in {"11", "12", "12.5", "13"}]

    start = args.from_stage or state.get("current_stage", handlers[0][0])
    active = False
    for stage, handler in handlers:
        if stage == start:
            active = True
        if not active:
            continue
        save_run_state(run_dir, {**load_run_state(run_dir), "current_stage": stage, "status": "running"})
        handler(run_dir)
        save_run_state(run_dir, {**load_run_state(run_dir), "last_completed_stage": stage})

    save_run_state(run_dir, {**load_run_state(run_dir), "status": "completed"})
    print(f"{args.phase} phase complete. run_id={run_id}")
    return 0
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat(auto-research): add durable resume stage loop"
```

---

# Task 8: New Run Bootstrap for Stages 0-10

This task adds the full end-to-end entry point. Stages 0-10 can initially be implemented by delegating to the existing auto-research orchestrator skill in draft mode, but the durable runner must still verify artifacts before moving on.

**Files:**
- Modify: `scripts/run_auto_research.py`
- Modify: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Add failing new-run bootstrap test**

Append to `tests/test_auto_research_runner_cli.py`:

```python
def test_main_with_topic_requires_bootstrap_to_create_run(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    monkeypatch.setattr("scripts.run_auto_research.bootstrap_new_run", lambda topic, phase: "demo-run")
    monkeypatch.setattr("scripts.run_auto_research.run_stage_11", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_13", lambda run_dir: None)
    (tmp_path / "research_runs" / "demo-run").mkdir(parents=True)

    rc = main(["--topic", "Demo topic", "--phase", "draft", "--from-stage", "11"])

    assert rc == 0
    assert (tmp_path / "research_runs" / "demo-run" / "run_control" / "run_state.json").exists()
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py::test_main_with_topic_requires_bootstrap_to_create_run -v
```

Expected: FAIL because `bootstrap_new_run` does not exist and `main()` rejects topic-only.

- [ ] **Step 3: Implement bootstrap using existing orchestrator skill**

Add before `main()`:

```python
def bootstrap_new_run(topic: str, phase: str) -> str:
    prompt = "\n".join([
        "Read AGENTS.md first.",
        "Use .agents/skills/auto-research-orchestrator/SKILL.md.",
        f"Run the auto-research pipeline for this topic through Stage 10 only: {topic}",
        "Stop after Stage 10 verified evidence is complete.",
        "Do not run Stage 11 or later.",
        "Print the final run_id on a line exactly like: RUN_ID=<run_id>",
    ])
    completed = subprocess.run(
        [
            "codex",
            "exec",
            "--cd",
            str(REPO_ROOT),
            "--model",
            "gpt-5.4-mini",
            "--ask-for-approval",
            "never",
            prompt,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"bootstrap failed: {completed.stderr}")
    for line in completed.stdout.splitlines():
        if line.startswith("RUN_ID="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("bootstrap did not print RUN_ID=<run_id>")
```

Then update `main()` so topic-only calls bootstrap:

```python
    run_id = args.run_id
    if run_id is None:
        run_id = bootstrap_new_run(args.topic, args.phase)
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_auto_research_runner_cli.py
git commit -m "feat(auto-research): bootstrap durable runs from topic"
```

---

# Task 9: Documentation and Operator Workflow

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`
- Modify: `docs/superpowers/plans/2026-05-10-auto-research-implementation-roadmap.md`

- [ ] **Step 1: Update orchestrator skill**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, add this section after `# Auto Research Orchestrator`:

```markdown
## Preferred durable runner

For end-to-end runs, prefer:

```bash
python scripts/run_auto_research.py --topic "<topic>" --phase draft
python scripts/run_auto_research.py --run-id <run_id> --phase write --resume
```

The Python runner owns durable stage state, shard manifests, artifact checks, retries, and deterministic merges. This skill remains the behavioral contract for every stage, but an interactive parent Codex session should not be the long-running control plane for full end-to-end runs.
```

- [ ] **Step 2: Update roadmap**

In `docs/superpowers/plans/2026-05-10-auto-research-implementation-roadmap.md`, add this after the SDK pilot paragraph:

```markdown
## Reliability Follow-Up

Before running more long end-to-end pilots, implement:

- `docs/superpowers/plans/2026-05-10-auto-research-durable-runner.md`

This runner fixes the observed failure mode where an interactive parent session stops after one shard returns while later shard notifications arrive after task completion.
```

- [ ] **Step 3: Verify doc text**

Run:

```bash
rg -n "Preferred durable runner|auto-research-durable-runner|interactive parent Codex session" .agents/skills/auto-research-orchestrator/SKILL.md docs/superpowers/plans/2026-05-10-auto-research-implementation-roadmap.md
```

Expected: matches all three phrases.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md docs/superpowers/plans/2026-05-10-auto-research-implementation-roadmap.md
git commit -m "docs(auto-research): document durable runner workflow"
```

---

# Task 10: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused runner tests**

Run:

```bash
env PYTHONPATH=. pytest tests/test_auto_research_runner_state.py tests/test_auto_research_runner_stage11.py tests/test_auto_research_runner_dispatch.py tests/test_auto_research_runner_cli.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```bash
env PYTHONPATH=. pytest tests/ -v
```

Expected: PASS.

- [ ] **Step 3: Validate interrupted-run resume point**

Run:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py --run-id advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939 --phase draft --resume --from-stage 11
test -f research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939/11_verified_graph/global_graph.json
test -f research_runs/advanced-llm-architecture-for-latent-reasoning-using-recurrent-looped-transformers-20260510-164939/12_taxonomy/outline.json
```

Expected:
- Runner does not rerun Stages 0-10.
- Stage 11 closes from existing fragments.
- Stage 12 creates `outline.json`.
- If a Codex worker fails, runner writes `run_control/stages/<stage>/...stderr.txt` and a `run_log.csv` failure row instead of silently stopping.

- [ ] **Step 4: Report**

Report:

- commits created;
- focused test results;
- full test result;
- whether interrupted run resumed past Stage 11;
- any Codex approval/model/tool blockers observed during non-interactive `codex exec`.

---

# Self-Review

**Spec coverage:** This plan addresses the failure mode directly: Stage 11 fragments can finish after an interactive parent stops, and the runner can still merge and continue. It also adds durable state, shard manifests, artifact checks, deterministic Stage 18 generation/validation, and resume behavior.

**Known risk:** `codex exec --ask-for-approval never` may expose MCP approval/config blockers in stages that need tools. The runner must treat that as a real operational blocker and write logs, not silently continue. If it blocks, the next plan should introduce a repo-local Codex profile for trusted swarn-auto-research MCP tools or use SDK calls for the affected one-shot stages.

**SDK relationship:** The SDK pilot remains useful for small JSON stages, but it is not the main reliability fix. The durable runner can later swap specific `ShardSpec` calls from `codex exec` to `sdk.codex.run_one_shot` without changing artifact completion rules.
