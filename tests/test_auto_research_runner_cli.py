from __future__ import annotations

import csv
import builtins
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

import scripts.auto_research_runner.chapters as chapters_mod
import scripts.auto_research_runner.cli as cli_mod
import scripts.auto_research_runner.packs as packs_mod
import scripts.auto_research_runner.process_cleanup as process_cleanup_mod
import scripts.auto_research_runner.shards as shards_mod
import scripts.auto_research_runner.stage_1_search as stage_1_search_mod
import scripts.auto_research_runner.stages as stages_mod
import scripts.auto_research_runner.validation as validation_mod
from scripts.auto_research_runner.cli import main
from scripts.auto_research_runner.packs import build_deterministic_stage_13_packs
from scripts.auto_research_runner.chapters import build_chapter_targets
from scripts.auto_research_runner.shards import run_deterministic_command, run_shards
from scripts.auto_research_runner.shared_types import ShardSpec, Stage8MarkdownUnavailable
from scripts.auto_research_runner.stages import (
    bootstrap_new_run,
    run_stage_1,
    run_stage_2,
    run_stage_3,
    run_stage_4,
    run_stage_5,
    run_stage_6,
    run_stage_7,
    run_stage_8,
    run_stage_9,
    run_stage_10,
    run_stage_11,
    run_stage_13,
    run_stage_14,
    run_stage_15,
    run_stage_16,
    run_stage_18,
)
from scripts.auto_research_runner.state import save_run_state
from scripts.auto_research_runner.validation import (
    validate_bootstrap_stage_0_10_contract,
    validate_stage_1_keep_all_contract,
)

# Tests refer to many helpers via `runner.X`. After the refactor those helpers
# live in different modules; the alias below keeps the tests readable by
# routing each name to the canonical module.
runner = stages_mod


class _FakeResponse:
    def __init__(self, *, status_code=200, text="# Paper\n", url="https://arxiv2md.org/api/markdown"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.request = type("Request", (), {"method": "GET"})()

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error


def test_default_shard_timeout_allows_long_verifier_turns():
    assert shards_mod.DEFAULT_SHARD_TIMEOUT_SECONDS == 3 * 3600


def test_effective_max_workers_caps_default_burden(monkeypatch):
    monkeypatch.delenv("SWARN_MAX_EFFECTIVE_WORKERS", raising=False)

    assert shards_mod._effective_max_workers(20) == 20


def test_effective_max_workers_uses_stage_default_caps(monkeypatch):
    monkeypatch.delenv("SWARN_MAX_EFFECTIVE_WORKERS", raising=False)
    for stage in ("2", "3", "6", "8", "9", "10", "11", "13", "14", "15", "16"):
        monkeypatch.delenv(f"SWARN_STAGE_{stage}_MAX_EFFECTIVE_WORKERS", raising=False)

    assert shards_mod._effective_max_workers(20, stage="2") == 20
    assert shards_mod._effective_max_workers(20, stage="3") == 20
    assert shards_mod._effective_max_workers(20, stage="6") == 10
    assert shards_mod._effective_max_workers(20, stage="8") == 20
    assert shards_mod._effective_max_workers(20, stage="9") == 20
    assert shards_mod._effective_max_workers(20, stage="10") == 20
    assert shards_mod._effective_max_workers(20, stage="11") == 10
    assert shards_mod._effective_max_workers(20, stage="13") == 5
    assert shards_mod._effective_max_workers(20, stage="14") == 10
    assert shards_mod._effective_max_workers(20, stage="15") == 5
    assert shards_mod._effective_max_workers(20, stage="16") == 20


def test_effective_max_workers_allows_env_override(monkeypatch):
    monkeypatch.setenv("SWARN_MAX_EFFECTIVE_WORKERS", "4")

    assert shards_mod._effective_max_workers(20) == 4


def test_effective_max_workers_allows_stage_6_env_override(monkeypatch):
    monkeypatch.setenv("SWARN_MAX_EFFECTIVE_WORKERS", "10")
    monkeypatch.setenv("SWARN_STAGE_6_MAX_EFFECTIVE_WORKERS", "3")

    assert shards_mod._effective_max_workers(20, stage="6") == 3


def test_effective_max_workers_allows_stage_env_override(monkeypatch):
    monkeypatch.setenv("SWARN_MAX_EFFECTIVE_WORKERS", "20")
    monkeypatch.setenv("SWARN_STAGE_10_MAX_EFFECTIVE_WORKERS", "7")

    assert shards_mod._effective_max_workers(20, stage="10") == 7


def _write_fake_proc(proc_root, pid, cmdline, cwd):
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True)
    (proc_dir / "cmdline").write_bytes(
        b"\0".join(str(part).encode() for part in cmdline) + b"\0"
    )
    (proc_dir / "cwd").symlink_to(cwd)


def test_find_research_mcp_pids_selects_only_repo_mcp_processes(tmp_path):
    proc_root = tmp_path / "proc"
    repo = tmp_path / "repo"
    other_repo = tmp_path / "other"
    repo.mkdir()
    other_repo.mkdir()
    _write_fake_proc(proc_root, 101, ["uv", "run", "swarn-auto-research-mcp"], repo)
    _write_fake_proc(
        proc_root,
        102,
        [
            str(repo / ".venv" / "bin" / "python3"),
            str(repo / ".venv" / "bin" / "swarn-auto-research-mcp"),
        ],
        repo,
    )
    _write_fake_proc(proc_root, 103, ["uv", "run", "other-tool"], repo)
    _write_fake_proc(proc_root, 104, ["uv", "run", "swarn-auto-research-mcp"], other_repo)

    assert process_cleanup_mod._find_research_mcp_pids(
        proc_root=proc_root,
        repo_root=repo,
        current_pid=999,
    ) == [101, 102]


def test_run_deterministic_command_logs_failure(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    completed = type(
        "Completed",
        (),
        {"returncode": 2, "stdout": "bad stdout", "stderr": "bad stderr"},
    )()

    with patch("scripts.auto_research_runner.shards.subprocess.run", return_value=completed):
        try:
            run_deterministic_command(run, "18", ["python", "-m", "demo"])
        except RuntimeError as error:
            assert str(error) == "stage 18 command failed: python -m demo"
        else:
            raise AssertionError("run_deterministic_command should fail")

    stage_dir = run / "run_control" / "stages" / "18"
    assert (stage_dir / "last_stdout.txt").read_text() == "bad stdout"
    assert (stage_dir / "last_stderr.txt").read_text() == "bad stderr"
    assert "18,failed,python -m demo" in (run / "run_log.csv").read_text()


def test_run_deterministic_command_logs_launch_error(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)

    with patch(
        "scripts.auto_research_runner.shards.subprocess.run",
        side_effect=FileNotFoundError("missing command"),
    ):
        try:
            run_deterministic_command(run, "18", ["missing-command"])
        except RuntimeError as error:
            assert str(error) == "stage 18 command failed: missing-command"
        else:
            raise AssertionError("run_deterministic_command should fail")

    stage_dir = run / "run_control" / "stages" / "18"
    assert (stage_dir / "last_stdout.txt").read_text() == ""
    assert "FileNotFoundError" in (stage_dir / "last_stderr.txt").read_text()
    assert "18,failed,missing-command" in (run / "run_log.csv").read_text()


def test_run_shards_honors_max_workers_20(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    active = 0
    max_seen = 0
    lock = threading.Lock()

    def fake_run(cmd, cwd, text, stdout, stderr, timeout):
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        try:
            output_path = run / cmd[-1]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok\n")
            time.sleep(0.03)
            return subprocess.CompletedProcess(cmd, 0)
        finally:
            with lock:
                active -= 1

    specs = [
        ShardSpec(
            stage="14",
            shard_id=f"parallel-{idx:03d}",
            agent="method_chapter_writer",
            model="gpt-5.4",
            prompt=f"out/{idx}.txt",
            expected_outputs=[f"out/{idx}.txt"],
        )
        for idx in range(20)
    ]

    with patch("scripts.auto_research_runner.shards.subprocess.run", side_effect=fake_run):
        run_shards(run, specs, max_workers=20, executor="cli")

    assert max_seen > 1
    assert all((run / f"out/{idx}.txt").exists() for idx in range(20))


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

    monkeypatch.setattr(shards_mod, "_run_shard_attempt", fail_attempt)

    with pytest.raises(RuntimeError):
        shards_mod._run_single_shard(run_dir, spec, max_retries=0)

    stderr = (
        run_dir
        / "run_control"
        / "stages"
        / "99"
        / "shards"
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


def test_run_stage_18_runs_generate_then_validate(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    (run / "14_chapters" / "book" / "appendices").mkdir(parents=True)
    (run / "16_book").mkdir(parents=True)
    (run / "16_book" / "SUMMARY.md").write_text("# Summary\n")
    (run / "16_book" / "sidebar.json").write_text(json.dumps([]))
    (run / "14_chapters" / "book" / "appendices" / "references.md").write_text(
        "# References\n"
    )

    with patch("scripts.auto_research_runner.stages.run_deterministic_command") as command:
        run_stage_18(Path(run))

    assert command.call_count == 2
    generate_cmd = command.call_args_list[0].args[2]
    validate_cmd = command.call_args_list[1].args[2]
    assert command.call_args_list[0].args[:2] == (run, "18")
    assert command.call_args_list[1].args[:2] == (run, "18")
    assert generate_cmd[1:] == [
        "-m",
        "swarn_research_mcp.research_book",
        str(run),
        "--generate",
    ]
    assert validate_cmd[1:] == [
        "-m",
        "swarn_research_mcp.research_book",
        str(run),
        "--validate",
    ]


def test_run_stage_1_dispatches_query_planner_for_search_plan_only(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    calls = []
    ids = [f"2501.{idx:05d}" for idx in range(40)]

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend(specs)
        (run / "00_input").mkdir(parents=True, exist_ok=True)
        aspects = [
            {
                "aspect_id": f"aspect_{idx}",
                "normal_queries": [f"normal {idx}"],
                "survey_queries": ([f"survey {idx}"] if idx < 3 else []),
                "positive_keywords": [f"keyword {idx}"],
            }
            for idx in range(4)
        ]
        (run / "00_input" / "search_plan.json").write_text(
            json.dumps({"topic": "Demo", "aspects": aspects})
        )

    async def fake_bulk_normal_start_search(*args, output_dir=None, **kwargs):
        bulk_path = Path(output_dir) / "bulk_search_results_123.json"
        bulk_path.write_text(json.dumps({"papers": ids}))
        return {
            "papers": {arxiv_id: "abstract" for arxiv_id in ids},
            "total_kept": len(ids),
            "output_path": str(bulk_path),
        }

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)
    monkeypatch.setattr(
        "swarn_research_mcp.tools.paper_search.bulk_normal_start_search",
        fake_bulk_normal_start_search,
    )

    run_stage_1(run)

    assert len(calls) == 1
    assert calls[0].stage == "1"
    assert calls[0].agent == "query_planner"
    assert "Run Stage 1 only" in calls[0].prompt
    assert "Write 00_input/search_plan.json." in calls[0].prompt
    assert calls[0].expected_outputs == ["00_input/search_plan.json"]


def test_run_stage_1_materializes_seed_pool_from_search_plan(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "00_input").mkdir(parents=True, exist_ok=True)
    (run / "00_input" / "topic.md").write_text("Demo topic\n")
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    captured = {}

    def fake_run_shards(run_dir, specs, **kwargs):
        assert len(specs) == 1
        assert specs[0].expected_outputs == ["00_input/search_plan.json"]
        (run_dir / "00_input" / "search_plan.json").write_text(
            json.dumps(
                {
                    "topic": "Demo topic",
                    "aspects": [
                        {
                            "aspect_id": f"aspect_{idx}",
                            "normal_queries": [f"normal {idx}"],
                            "survey_queries": ([f"survey {idx}"] if idx < 3 else []),
                            "positive_keywords": [f"keyword {idx}"],
                            "negative_keywords": [f"negative {idx}"],
                        }
                        for idx in range(4)
                    ],
                    "global_negative_keywords": ["global noise"],
                }
            )
        )

    async def fake_bulk_normal_start_search(
        queries,
        survey_queries,
        positive_keywords,
        negative_keywords,
        output_dir=None,
    ):
        captured["queries"] = queries
        captured["survey_queries"] = survey_queries
        captured["positive_keywords"] = positive_keywords
        captured["negative_keywords"] = negative_keywords
        captured["output_dir"] = output_dir
        bulk_path = Path(output_dir) / "bulk_search_results_123.json"
        bulk_path.write_text(json.dumps({"papers": ids}))
        return {
            "papers": {arxiv_id: f"abstract {arxiv_id}" for arxiv_id in ids},
            "total_kept": len(ids),
            "output_path": str(bulk_path),
        }

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)
    monkeypatch.setattr(
        "swarn_research_mcp.tools.paper_search.bulk_normal_start_search",
        fake_bulk_normal_start_search,
    )

    run_stage_1(run)

    assert captured["queries"] == [f"normal {idx}" for idx in range(4)]
    assert captured["survey_queries"] == [f"survey {idx}" for idx in range(3)]
    assert captured["positive_keywords"] == [f"keyword {idx}" for idx in range(4)]
    assert captured["negative_keywords"] == [f"negative {idx}" for idx in range(4)] + [
        "global noise"
    ]
    assert Path(captured["output_dir"]) == run / "01_seed_pool"
    assert (run / "01_seed_pool" / "seed_pool_raw.json").exists()
    assert (run / "02_paper_pool" / "paper_pool.json").exists()
    assert (run / "02_paper_pool" / "paper_pool.csv").exists()
    report = json.loads((run / "02_paper_pool" / "candidate_pool_report.json").read_text())
    assert report["raw_kept"] == 40
    assert report["selected_total"] == 40
    assert report["selection_policy"] == "keep_all_bulk_search_results"


def test_build_stage_1_search_inputs_caps_bulk_queries_to_aspect_budget():
    search_plan = {
        "aspects": [
            {
                "aspect_id": f"aspect_{idx}",
                "normal_queries": [f"normal {idx} a", f"normal {idx} b"],
                "survey_queries": [f"survey {idx} a", f"survey {idx} b"],
                "positive_keywords": [f"keyword {idx}"],
                "negative_keywords": [f"negative {idx}"],
            }
            for idx in range(6)
        ],
        "global_negative_keywords": ["global noise"],
    }

    queries, survey_queries, positive_keywords, negative_keywords = (
        stage_1_search_mod._build_stage_1_search_inputs(search_plan)
    )

    assert queries == [f"normal {idx} a" for idx in range(5)]
    assert survey_queries == [f"survey {idx} a" for idx in range(3)]
    assert positive_keywords == [f"keyword {idx}" for idx in range(6)]
    assert negative_keywords == [f"negative {idx}" for idx in range(6)] + [
        "global noise"
    ]


def test_validate_stage_1_keep_all_contract_allows_empty_per_aspect_survey_queries(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    search_plan_path = run / "00_input" / "search_plan.json"
    search_plan = json.loads(search_plan_path.read_text())
    for idx, aspect in enumerate(search_plan["aspects"]):
        aspect["survey_queries"] = [f"survey query {idx}"] if idx < 3 else []
    search_plan_path.write_text(json.dumps(search_plan))

    assert validate_stage_1_keep_all_contract(run) == ids


def test_stage_1_later_resume_allows_legacy_overbudget_query_plan(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    search_plan_path = run / "00_input" / "search_plan.json"
    search_plan = json.loads(search_plan_path.read_text())
    for idx, aspect in enumerate(search_plan["aspects"]):
        aspect["normal_queries"] = [f"normal {idx} a", f"normal {idx} b", f"normal {idx} c"]
        aspect["survey_queries"] = [f"survey {idx}"]
    search_plan_path.write_text(json.dumps(search_plan))

    assert validate_stage_1_keep_all_contract(run) == ids
    with pytest.raises(RuntimeError, match="normal query count"):
        validate_stage_1_keep_all_contract(run, enforce_query_budget=True)


def test_run_stage_1_uses_bulk_search_config_by_default(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    captured = {}
    monkeypatch.delenv("SWARN_BULK_SEARCH_CONFIG", raising=False)

    def fake_run_shards(run_dir, specs, **kwargs):
        (run_dir / "00_input").mkdir(parents=True, exist_ok=True)
        (run_dir / "00_input" / "search_plan.json").write_text(
            json.dumps(
                {
                    "topic": "Demo",
                    "aspects": [
                        {
                            "aspect_id": f"aspect_{idx}",
                            "normal_queries": [f"normal {idx}"],
                            "survey_queries": ([f"survey {idx}"] if idx < 3 else []),
                            "positive_keywords": [f"keyword {idx}"],
                        }
                        for idx in range(4)
                    ],
                }
            )
        )

    async def fake_bulk_normal_start_search(*args, output_dir=None, **kwargs):
        captured["config"] = os.environ.get("SWARN_BULK_SEARCH_CONFIG")
        bulk_path = Path(output_dir) / "bulk_search_results_123.json"
        bulk_path.write_text(json.dumps({"papers": ids}))
        return {
            "papers": {arxiv_id: "abstract" for arxiv_id in ids},
            "total_kept": len(ids),
            "output_path": str(bulk_path),
        }

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)
    monkeypatch.setattr(
        "swarn_research_mcp.tools.paper_search.bulk_normal_start_search",
        fake_bulk_normal_start_search,
    )

    run_stage_1(run)

    assert captured["config"] == str(
        runner.REPO_ROOT / "swarn_research_mcp" / "bulk_search_config.json"
    )


def _write_stage_1_contract_artifacts(run, *, raw_count=45, selected_count=None):
    if selected_count is None:
        selected_count = raw_count
    (run / "00_input").mkdir(parents=True, exist_ok=True)
    (run / "01_seed_pool").mkdir(parents=True, exist_ok=True)
    (run / "02_paper_pool").mkdir(parents=True, exist_ok=True)
    aspects = [
        {
            "aspect_id": f"aspect_{idx}",
            "normal_queries": [f"normal {idx}"],
            "survey_queries": ([f"survey {idx}"] if idx < 3 else []),
            "positive_keywords": [f"keyword {idx}"],
        }
        for idx in range(4)
    ]
    (run / "00_input" / "search_plan.json").write_text(
        json.dumps({"topic": "Demo", "aspects": aspects})
    )
    raw_ids = [f"2501.{idx:05d}" for idx in range(raw_count)]
    selected_ids = raw_ids[:selected_count]
    bulk_path = run / "01_seed_pool" / "bulk_search_results_123.json"
    bulk_path.write_text(json.dumps({"papers": raw_ids}))
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": {arxiv_id: "abstract" for arxiv_id in raw_ids},
                "total_kept": len(raw_ids),
                "output_path": str(bulk_path),
            }
        )
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in selected_ids])
    )
    (run / "02_paper_pool" / "paper_pool.csv").write_text(
        "arxiv_id\n" + "\n".join(selected_ids) + "\n"
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(raw_ids),
                "selected_total": len(raw_ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )


def test_run_stage_1_rejects_bulk_search_below_minimum_pool(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    ids = [f"2501.{idx:05d}" for idx in range(39)]

    def fake_run_shards(run_dir, specs, **kwargs):
        (run_dir / "00_input").mkdir(parents=True, exist_ok=True)
        (run_dir / "00_input" / "search_plan.json").write_text(
            json.dumps(
                {
                    "topic": "Demo",
                    "aspects": [
                        {
                            "aspect_id": f"aspect_{idx}",
                            "normal_queries": [f"normal {idx}"],
                            "survey_queries": ([f"survey {idx}"] if idx < 3 else []),
                            "positive_keywords": [f"keyword {idx}"],
                        }
                        for idx in range(4)
                    ],
                }
            )
        )

    async def fake_bulk_normal_start_search(*args, output_dir=None, **kwargs):
        bulk_path = Path(output_dir) / "bulk_search_results_123.json"
        bulk_path.write_text(json.dumps({"papers": ids}))
        return {
            "papers": {arxiv_id: "abstract" for arxiv_id in ids},
            "total_kept": len(ids),
            "output_path": str(bulk_path),
        }

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)
    monkeypatch.setattr(
        "swarn_research_mcp.tools.paper_search.bulk_normal_start_search",
        fake_bulk_normal_start_search,
    )

    with pytest.raises(RuntimeError) as error:
        run_stage_1(run)

    assert "paper_pool.json must contain at least 40 papers" in str(error.value)


def test_run_stage_1_validates_existing_primary_artifacts_before_skip(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    _write_stage_1_contract_artifacts(run, raw_count=45, selected_count=40)

    def fail_run_shards(*args, **kwargs):
        raise AssertionError("run_shards should not be called for existing primary artifacts")

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fail_run_shards)

    with pytest.raises(RuntimeError) as error:
        run_stage_1(run)

    assert "paper_pool.json must contain every paper kept by bulk search" in str(error.value)


def test_run_stage_2_chunks_paper_pool_into_weak_evidence_specs(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    ids = [f"2501.{idx:05d}" for idx in range(12)]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps({"reader_needed_concepts": ["concept"]}))

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_2(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [5, 5, 2]
    assert all(spec.agent == "weak_evidence_extractor" for spec in captured)
    assert all("Run Stage 2 only" in spec.prompt for spec in captured)
    assert all("arxiv_ids" in spec.prompt for spec in captured)


def test_run_stage_3_chunks_paper_pool_and_merges_weak_graph_fragments(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    ids = [f"2501.{idx:05d}" for idx in range(12)]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                arxiv_id = Path(rel_path).stem
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps(
                        {
                            "nodes": [
                                {"id": arxiv_id, "type": "Paper"},
                                {"id": "shared-method", "type": "Method"},
                            ],
                            "edges": [
                                {
                                    "src": arxiv_id,
                                    "dst": "shared-method",
                                    "type": "USES",
                                    "confidence": "weak",
                                }
                            ],
                        }
                    )
                )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_3(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [5, 5, 2]
    assert all(spec.agent == "weak_graph_extractor" for spec in captured)
    graph = json.loads((run / "05_weak_graph" / "weak_global_graph.json").read_text())
    assert len(graph["nodes"]) == 13
    assert len(graph["edges"]) == 12


def test_run_stage_3_validates_existing_global_graph_before_skip(tmp_path):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(json.dumps([{"arxiv_id": "1.1"}]))
    (run / "05_weak_graph" / "fragments").mkdir(parents=True)
    (run / "05_weak_graph" / "fragments" / "1.1.json").write_text(
        json.dumps({"nodes": [{"id": "1.1"}], "edges": []})
    )
    (run / "05_weak_graph" / "weak_global_graph.json").write_text(
        json.dumps({"nodes": [], "edges": []})
    )

    with pytest.raises(RuntimeError, match="at least one node"):
        run_stage_3(run)


def test_run_stage_4_dispatches_knowledge_base_reader(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        out = run_dir / "06_expansion" / "known_concepts_snapshot.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"known_concepts": []}))

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_4(run)

    assert len(captured) == 1
    assert captured[0].agent == "knowledge_base_reader"
    assert captured[0].expected_outputs == ["06_expansion/known_concepts_snapshot.json"]


def test_run_stage_5_dispatches_classifier_and_logs_queue_count(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    captured = []
    concepts = ["gap one", "gap two"]

    def fake_aggregate(run_dir):
        out_dir = run_dir / "06_expansion"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "gap_candidates_digest.json").write_text(json.dumps({
            "candidates": [{"concept": concept} for concept in concepts]
        }))

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        out_dir = run_dir / "06_expansion"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "knowledge_gap_report.json").write_text(json.dumps({
            "known": [],
            "unknown_minor": [],
            "knowledge_gaps": [{"concept": concept} for concept in concepts],
        }))
        (out_dir / "expansion_need_queue.json").write_text(
            json.dumps({"items": [
                {
                    "gap_id": "g1",
                    "concept": "gap one",
                    "priority": 0.70,
                    "search_queries": ["gap one arxiv", "gap one survey"],
                },
                {
                    "gap_id": "g2",
                    "concept": "gap two",
                    "priority": 0.71,
                    "search_queries": ["gap two arxiv", "gap two survey"],
                },
            ]})
        )
        (out_dir / "extracted_concepts.json").write_text(
            json.dumps({"concepts": [{"concept": concept} for concept in concepts]})
        )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_stage_5_aggregate", fake_aggregate)
    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_5(run)

    assert len(captured) == 1
    assert captured[0].agent == "knowledge_gap_classifier"
    assert "queue_items=2" in (run / "run_log.csv").read_text()


def test_run_stage_6_writes_skipped_outputs_when_queue_is_empty(tmp_path):
    run = tmp_path / "run"
    (run / "06_expansion").mkdir(parents=True)
    (run / "06_expansion" / "expansion_need_queue.json").write_text(json.dumps({"items": []}))

    run_stage_6(run)

    assert json.loads((run / "06_expansion" / "expansion_round_01.json").read_text()) == {
        "items": [],
        "status": "skipped",
    }
    assert (run / "06_expansion" / "accepted_candidates.csv").read_text().startswith("arxiv_id,")
    assert (run / "06_expansion" / "rejected_candidates.csv").read_text().startswith("arxiv_id,")


def test_run_stage_6_dispatches_one_expansion_shard_per_gap_and_merges(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": "2401.00001", "title": "Seed"}])
    )
    (run / "02_paper_pool" / "paper_pool.csv").write_text("arxiv_id\n2401.00001\n")
    (run / "06_expansion").mkdir(parents=True)
    (run / "06_expansion" / "expansion_need_queue.json").write_text(
        json.dumps({"items": [{"gap_id": "g1"}, {"gap_id": "g2"}]})
    )
    monkeypatch.delenv("SWARN_CODEX_RELEVANCE_SESSION_LIMIT", raising=False)
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        assert os.environ["SWARN_CODEX_RELEVANCE_SESSION_LIMIT"] == "1"
        captured.extend(specs)
        expansion_dir = run_dir / "06_expansion"
        for spec in specs:
            shard_id = spec.shard_id
            (expansion_dir / f"expansion_round_01_shard_{shard_id}.json").write_text(
                json.dumps({"items": [{"shard_id": shard_id}]})
            )
            (expansion_dir / f"accepted_candidates_shard_{shard_id}.csv").write_text(
                "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
                f"2501.{shard_id[-3:]},g,{shard_id},Title,foundational,0.9,needed\n"
            )
            (expansion_dir / f"rejected_candidates_shard_{shard_id}.csv").write_text(
                "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
            )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)
    monkeypatch.setattr("scripts.auto_research_runner.stages.run_stage_2", lambda *args, **kwargs: None)
    monkeypatch.setattr("scripts.auto_research_runner.stages.run_stage_3", lambda *args, **kwargs: None)

    run_stage_6(run, max_workers=20)

    assert [spec.shard_id for spec in captured] == ["expansion-001", "expansion-002"]
    assert all(spec.agent == "paper_expander" for spec in captured)
    assert "SWARN_CODEX_RELEVANCE_SESSION_LIMIT" not in os.environ
    round_data = json.loads((run / "06_expansion" / "expansion_round_01.json").read_text())
    assert round_data["status"] == "completed"
    assert len(round_data["items"]) == 2
    assert "2501.001" in (run / "06_expansion" / "accepted_candidates.csv").read_text()
    pool = json.loads((run / "02_paper_pool" / "paper_pool.json").read_text())
    assert [paper["arxiv_id"] for paper in pool] == ["2401.00001", "2501.001", "2501.002"]
    assert pool[1]["source"] == "knowledge_gap_expansion"
    assert pool[1]["added_for_gap"] == "expansion-001"


def test_run_stage_6_merge_accepts_new_shard_schema(tmp_path):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(json.dumps([{"arxiv_id": "2401.00001"}]))
    (run / "02_paper_pool" / "paper_pool.csv").write_text("arxiv_id\n2401.00001\n")
    expansion_dir = run / "06_expansion"
    expansion_dir.mkdir(parents=True)
    (expansion_dir / "expansion_round_01_shard_expansion-001.json").write_text(
        json.dumps({
            "status": "completed",
            "shard_id": "expansion-001",
            "gap_item": {"gap_id": "g1", "concept": "ReAct"},
            "gap_search": {"total_input": 10, "total_kept": 2},
            "accepted_candidates": [{"arxiv_id": "2210.03629"}],
            "rejected_candidates": [{"arxiv_id": "2301.00001"}],
        })
    )
    (expansion_dir / "accepted_candidates_shard_expansion-001.csv").write_text(
        "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
        "2210.03629,g1,ReAct,ReAct,canonical,0.99,needed\n"
    )
    (expansion_dir / "rejected_candidates_shard_expansion-001.csv").write_text(
        "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
        "2301.00001,g1,ReAct,Other,method,0.5,off-topic\n"
    )

    runner.merge_expansion_shards(run, ["expansion-001"])

    round_data = json.loads((expansion_dir / "expansion_round_01.json").read_text())
    assert round_data["status"] == "completed"
    assert len(round_data["items"]) == 1
    assert round_data["items"][0]["gap_item"]["concept"] == "ReAct"
    pool = json.loads((run / "02_paper_pool" / "paper_pool.json").read_text())
    assert [paper["arxiv_id"] for paper in pool] == ["2401.00001", "2210.03629"]
    assert pool[1]["added_for_gap"] == "ReAct"
    assert pool[1]["why_needed"] == "needed"


def test_run_stage_6_backfills_weak_artifacts_for_accepted_papers(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": "2401.00001"}])
    )
    (run / "02_paper_pool" / "paper_pool.csv").write_text("arxiv_id\n2401.00001\n")
    (run / "04_weak_evidence").mkdir(parents=True)
    (run / "04_weak_evidence" / "2401.00001.json").write_text(
        json.dumps({"reader_needed_concepts": ["seed"]})
    )
    (run / "05_weak_graph" / "fragments").mkdir(parents=True)
    (run / "05_weak_graph" / "fragments" / "2401.00001.json").write_text(
        json.dumps({"nodes": [{"id": "2401.00001"}], "edges": []})
    )
    (run / "05_weak_graph" / "weak_global_graph.json").write_text(
        json.dumps({"nodes": [{"id": "2401.00001"}], "edges": []})
    )
    (run / "06_expansion").mkdir(parents=True)
    (run / "06_expansion" / "expansion_need_queue.json").write_text(
        json.dumps({"items": [{"gap_id": "g1"}]})
    )
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        expansion_dir = run_dir / "06_expansion"
        for spec in specs:
            shard_id = spec.shard_id
            (expansion_dir / f"expansion_round_01_shard_{shard_id}.json").write_text(
                json.dumps({"status": "completed", "items": [{"shard_id": shard_id}]})
            )
            (expansion_dir / f"accepted_candidates_shard_{shard_id}.csv").write_text(
                "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
                "2501.00001,g1,ReAct,ReAct,canonical,0.99,needed\n"
            )
            (expansion_dir / f"rejected_candidates_shard_{shard_id}.csv").write_text(
                "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
            )

    def fake_stage_2(*args, **kwargs):
        calls.append("2")
        (run / "04_weak_evidence" / "2501.00001.json").write_text(
            json.dumps({"reader_needed_concepts": ["ReAct"]})
        )

    def fake_stage_3(*args, **kwargs):
        calls.append("3")
        (run / "05_weak_graph" / "fragments" / "2501.00001.json").write_text(
            json.dumps({"nodes": [{"id": "2501.00001"}], "edges": []})
        )
        (run / "05_weak_graph" / "weak_global_graph.json").write_text(
            json.dumps({"nodes": [{"id": "2401.00001"}, {"id": "2501.00001"}], "edges": []})
        )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)
    monkeypatch.setattr("scripts.auto_research_runner.stages.run_stage_2", fake_stage_2)
    monkeypatch.setattr("scripts.auto_research_runner.stages.run_stage_3", fake_stage_3)

    run_stage_6(run)

    assert calls == ["2", "3"]


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

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_7(run)

    assert len(calls) == 1
    assert calls[0].agent == "paper_ranker"
    assert "Run Stage 7 scoring only" in calls[0].prompt
    assert "paper_scores.csv" in calls[0].prompt


def test_run_stage_7_normalizes_reduced_promotion_candidates_csv(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    ids = ["1.1", "1.2"]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )

    def fake_run_shards(run_dir, specs, **kwargs):
        header = (
            "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
            "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
        )
        rows = "1.1,1,1,1,1,1,1,0,0.9\n1.2,0,0,0,0,0,0,0,0.1\n"
        (run / "07_scoring" / "paper_scores.csv").write_text(header + rows)
        (run / "07_scoring" / "promotion_candidates.csv").write_text(
            "arxiv_id,final_score,reason\n1.1,0.9,top\n1.2,0.1,tail\n"
        )
        (run / "07_scoring" / "promoted_papers.json").write_text(
            json.dumps(
                {
                    "promoted_papers": [
                        {"arxiv_id": "1.2", "final_score": 0.1, "reason": "tail"},
                        {"arxiv_id": "1.1", "final_score": 0.9, "reason": "top"},
                    ]
                }
            )
        )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_7(run)

    candidates = (run / "07_scoring" / "promotion_candidates.csv").read_text()
    promoted = json.loads((run / "07_scoring" / "promoted_papers.json").read_text())
    assert "topic_relevance" in candidates
    assert "reason" not in candidates.splitlines()[0]
    assert candidates.splitlines()[1].startswith("1.1,")
    assert promoted["promoted_papers"] == [{"arxiv_id": "1.1", "final_score": 0.9, "reason": "top"}]


def test_run_stage_7_normalizes_top_level_promoted_papers_list(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    ids = ["1.1", "1.2"]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )

    def fake_run_shards(run_dir, specs, **kwargs):
        header = (
            "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
            "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
        )
        rows = "1.1,1,1,1,1,1,1,0,0.9\n1.2,0,0,0,0,0,0,0,0.1\n"
        (run / "07_scoring" / "paper_scores.csv").write_text(header + rows)
        (run / "07_scoring" / "promotion_candidates.csv").write_text(header + rows)
        (run / "07_scoring" / "promoted_papers.json").write_text(
            json.dumps([
                {"arxiv_id": "1.2", "final_score": 0.1, "reason": "tail"},
                {"arxiv_id": "1.1", "final_score": 0.9, "reason": "top"},
            ])
        )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_7(run)

    promoted = json.loads((run / "07_scoring" / "promoted_papers.json").read_text())
    assert promoted["promoted_papers"] == [{"arxiv_id": "1.1", "final_score": 0.9, "reason": "top"}]


def _write_promoted_papers(run, ids):
    (run / "07_scoring").mkdir(parents=True, exist_ok=True)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": arxiv_id} for arxiv_id in ids]})
    )


def _write_valid_pageindex(run, arxiv_id):
    (run / "09_pageindex" / "trees").mkdir(parents=True, exist_ok=True)
    (run / "09_pageindex" / "nodes").mkdir(parents=True, exist_ok=True)
    (run / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "root": {
                    "id": "s.00",
                    "title": "(root)",
                    "children": [
                        {
                            "id": "s.01",
                            "title": "Paper",
                            "level": 1,
                            "start_line": 1,
                            "end_line": 1,
                            "parent_id": "s.00",
                            "summary": "Paper.",
                            "children": [],
                        }
                    ],
                },
            }
        )
    )
    (run / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json").write_text(
        json.dumps(
            {
                "s.01": {
                    "id": "s.01",
                    "title": "Paper",
                    "level": 1,
                    "start_line": 1,
                    "end_line": 1,
                    "parent_id": "s.00",
                    "summary": "Paper.",
                }
            }
        )
    )


def test_run_stage_8_fetches_full_markdown_without_agent_shards(tmp_path, monkeypatch):
    run = tmp_path / "run"
    ids = ["1.1", "1.2"]
    _write_promoted_papers(run, ids)
    fetched = []

    def fake_fetch(arxiv_id):
        fetched.append(arxiv_id)
        return f"# Paper {arxiv_id}\n"

    monkeypatch.setattr("scripts.auto_research_runner.stages._fetch_arxiv_markdown_sync", fake_fetch)
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.run_shards",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Stage 8 should not dispatch agents")),
    )

    run_stage_8(run, max_workers=10)

    assert sorted(fetched) == ids
    assert (run / "08_full_markdown" / "1.1.md").read_text() == "# Paper 1.1\n"
    assert (run / "08_full_markdown" / "1.2.md").read_text() == "# Paper 1.2\n"
    manifest = json.loads(
        (run / "run_control" / "stages" / "8" / "shards" / "full-markdown-1.1.json").read_text()
    )
    assert manifest["executor"] == "direct"
    assert manifest["status"] == "completed"


def test_stage_8_direct_fetch_uses_bounded_requests_without_arxiv_service_import(monkeypatch):
    captured = {}
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"swarn_research_mcp.services.arxiv", "swarn_research_mcp.services.utils"}:
            raise AssertionError(f"Stage 8 fetch must not import {name}")
        return real_import(name, *args, **kwargs)

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(text="# Paper\n")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr("scripts.auto_research_runner.stages.requests.get", fake_get)

    assert runner._fetch_arxiv_markdown_sync("1.1") == "# Paper\n"
    assert captured["url"] == runner.ARXIV2MD_MARKDOWN_URL
    assert captured["kwargs"]["params"] == {"url": "1.1", "remove_toc": "false"}
    assert captured["kwargs"]["timeout"] > 0


def test_stage_8_direct_fetch_classifies_permanent_404_as_unavailable(monkeypatch):
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=404, text="not found"),
    )

    with pytest.raises(Stage8MarkdownUnavailable):
        runner._fetch_arxiv_markdown_sync("missing")


def test_stage_8_direct_fetch_keeps_transient_errors_fatal(monkeypatch):
    for error in (
        requests.Timeout("timeout"),
        requests.ConnectionError("dns failed"),
    ):
        monkeypatch.setattr(
            "scripts.auto_research_runner.stages.requests.get",
            lambda *args, error=error, **kwargs: (_ for _ in ()).throw(error),
        )
        with pytest.raises(type(error)):
            runner._fetch_arxiv_markdown_sync("1.1")

    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=429, text="rate limited"),
    )
    with pytest.raises(requests.HTTPError):
        runner._fetch_arxiv_markdown_sync("1.1")

    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=500, text="server error"),
    )
    with pytest.raises(requests.HTTPError):
        runner._fetch_arxiv_markdown_sync("1.1")


def test_run_stage_8_reads_legacy_promoted_papers_without_mutating(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "07_scoring").mkdir(parents=True)
    promoted_path = run / "07_scoring" / "promoted_papers.json"
    promoted_path.write_text(
        json.dumps([
            {"arxiv_id": "1.1", "final_score": 0.9},
            {"arxiv_id": "1.2", "final_score": 0.1},
        ])
    )
    original = promoted_path.read_text()
    fetched = []

    def fake_fetch(arxiv_id):
        fetched.append(arxiv_id)
        return f"# Paper {arxiv_id}\n"

    monkeypatch.setattr("scripts.auto_research_runner.stages._fetch_arxiv_markdown_sync", fake_fetch)

    run_stage_8(run)

    assert fetched == ["1.1", "1.2"]
    assert (run / "08_full_markdown" / "1.1.md").exists()
    assert promoted_path.read_text() == original


def test_run_stage_8_records_failed_direct_fetch(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])

    def fake_fetch(arxiv_id):
        raise RuntimeError(f"network failed for {arxiv_id}")

    monkeypatch.setattr("scripts.auto_research_runner.stages._fetch_arxiv_markdown_sync", fake_fetch)

    with pytest.raises(RuntimeError, match="1 markdown fetch"):
        run_stage_8(run)

    manifest = json.loads(
        (run / "run_control" / "stages" / "8" / "shards" / "full-markdown-1.1.json").read_text()
    )
    assert manifest["executor"] == "direct"
    assert manifest["status"] == "failed"
    stderr = (
        run
        / "run_control"
        / "stages"
        / "8"
        / "shards"
        / "full-markdown-1.1.attempt-1.stderr.txt"
    ).read_text()
    assert "network failed for 1.1" in stderr


def test_run_stage_8_quarantines_empty_markdown_without_mutating_promoted(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1", "1.2"])

    def fake_fetch(arxiv_id):
        if arxiv_id == "1.1":
            return ""
        return f"# Paper {arxiv_id}\n"

    monkeypatch.setattr("scripts.auto_research_runner.stages._fetch_arxiv_markdown_sync", fake_fetch)

    run_stage_8(run, max_workers=2)

    assert not (run / "08_full_markdown" / "1.1.md").exists()
    assert (run / "08_full_markdown" / "1.2.md").exists()
    unavailable_csv = (run / "08_full_markdown" / "unavailable_markdown.csv").read_text()
    assert "1.1,Stage8MarkdownUnavailable" in unavailable_csv
    promoted = json.loads((run / "07_scoring" / "promoted_papers.json").read_text())
    assert [item["arxiv_id"] for item in promoted["promoted_papers"]] == ["1.1", "1.2"]
    assert not (run / "07_scoring" / "promoted_papers_before_stage8_filter.json").exists()
    assert runner.load_fulltext_available_promoted_arxiv_ids(run) == ["1.2"]
    manifest = json.loads(
        (run / "run_control" / "stages" / "8" / "shards" / "full-markdown-1.1.json").read_text()
    )
    assert manifest["status"] == "unavailable"


def test_run_stage_8_refetches_blank_existing_markdown(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("")
    fetched = []

    def fake_fetch(arxiv_id):
        fetched.append(arxiv_id)
        return "# Paper\n\nRecovered.\n"

    monkeypatch.setattr("scripts.auto_research_runner.stages._fetch_arxiv_markdown_sync", fake_fetch)

    run_stage_8(run)

    assert fetched == ["1.1"]
    assert (run / "08_full_markdown" / "1.1.md").read_text() == "# Paper\n\nRecovered.\n"


def test_run_stage_9_builds_pageindex_without_agent_shards(tmp_path, monkeypatch):
    run = tmp_path / "run"
    ids = ["1.1", "1.2"]
    _write_promoted_papers(run, ids)
    (run / "08_full_markdown").mkdir()
    (run / "08_full_markdown" / "1.1.md").write_text(
        "# Intro\n\nFirst sentence. Second sentence.\n\n## Details\n\nDetail sentence.\n"
    )
    (run / "08_full_markdown" / "1.2.md").write_text("# Only\n\nContent.\n")
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.run_shards",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Stage 9 should not dispatch agents")),
    )

    run_stage_9(run, max_workers=20)

    tree = json.loads((run / "09_pageindex" / "trees" / "1.1.tree.json").read_text())
    nodes = json.loads((run / "09_pageindex" / "nodes" / "1.1.nodes.json").read_text())
    assert tree["arxiv_id"] == "1.1"
    assert sorted(tree["root"]) == ["children", "id", "title"]
    assert tree["root"]["children"][0]["id"] == "s.01"
    assert tree["root"]["children"][0]["children"][0]["id"] == "s.01.01"
    assert "s.00" not in nodes
    assert nodes["s.01"]["summary"] == "First sentence."
    assert nodes["s.01.01"]["summary"] == "Detail sentence."
    manifest = json.loads(
        (run / "run_control" / "stages" / "9" / "shards" / "pageindex-1.1.json").read_text()
    )
    assert manifest["executor"] == "direct"
    assert manifest["status"] == "completed"


def test_run_stage_9_rebuilds_invalid_pageindex_and_skips_unavailable_markdown(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1", "1.2"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("")
    (run / "08_full_markdown" / "1.2.md").write_text("# Intro\n\nValid paper.\n")
    (run / "09_pageindex" / "trees").mkdir(parents=True)
    (run / "09_pageindex" / "nodes").mkdir(parents=True)
    (run / "09_pageindex" / "trees" / "1.2.tree.json").write_text('{"root":{"children":[]}}')
    (run / "09_pageindex" / "nodes" / "1.2.nodes.json").write_text("{}")
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.run_shards",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Stage 9 should not dispatch agents")),
    )

    run_stage_9(run, max_workers=2)

    assert not (run / "09_pageindex" / "trees" / "1.1.tree.json").exists()
    nodes = json.loads((run / "09_pageindex" / "nodes" / "1.2.nodes.json").read_text())
    assert list(nodes) == ["s.01"]
    assert nodes["s.01"]["summary"] == "Valid paper."


def test_run_stage_9_uses_facade_pageindex_validator(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Intro\n\nValid paper.\n")
    calls = []

    def fake_pageindex_valid(run_dir, arxiv_id):
        calls.append((run_dir, arxiv_id))
        return True

    monkeypatch.setattr("scripts.auto_research_runner.stages._pageindex_artifacts_valid", fake_pageindex_valid)
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages._build_pageindex_for_paper",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should be skipped")),
    )

    run_stage_9(run)

    assert calls == [(run, "1.1")]


def test_pageindex_validation_rejects_tree_flat_mismatch_and_bad_line_bounds(tmp_path):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Intro\n\nText.\n")
    _write_valid_pageindex(run, "1.1")
    assert runner._pageindex_artifacts_valid(run, "1.1")

    tree_path = run / "09_pageindex" / "trees" / "1.1.tree.json"
    nodes_path = run / "09_pageindex" / "nodes" / "1.1.nodes.json"
    tree = json.loads(tree_path.read_text())
    tree["root"]["children"][0]["id"] = "s.02"
    tree_path.write_text(json.dumps(tree))
    assert not runner._pageindex_artifacts_valid(run, "1.1")

    _write_valid_pageindex(run, "1.1")
    nodes = json.loads(nodes_path.read_text())
    nodes["s.02"] = dict(nodes["s.01"], id="s.02")
    nodes_path.write_text(json.dumps(nodes))
    assert not runner._pageindex_artifacts_valid(run, "1.1")

    _write_valid_pageindex(run, "1.1")
    nodes = json.loads(nodes_path.read_text())
    nodes["s.01"]["end_line"] = 99
    nodes_path.write_text(json.dumps(nodes))
    assert not runner._pageindex_artifacts_valid(run, "1.1")


def test_pageindex_validation_accepts_legacy_wrapped_nodes(tmp_path):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Intro\n")
    _write_valid_pageindex(run, "1.1")
    nodes_path = run / "09_pageindex" / "nodes" / "1.1.nodes.json"
    nodes = json.loads(nodes_path.read_text())
    nodes_path.write_text(json.dumps({"nodes": nodes}))

    assert runner._pageindex_artifacts_valid(run, "1.1")


def test_run_stage_9_records_direct_parse_failure(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages._build_pageindex_for_paper",
        lambda run_dir, arxiv_id: (_ for _ in ()).throw(RuntimeError("bad markdown")),
    )

    with pytest.raises(RuntimeError, match="1 PageIndex build"):
        run_stage_9(run)

    manifest = json.loads(
        (run / "run_control" / "stages" / "9" / "shards" / "pageindex-1.1.json").read_text()
    )
    assert manifest["executor"] == "direct"
    assert manifest["status"] == "failed"
    stderr = (
        run
        / "run_control"
        / "stages"
        / "9"
        / "shards"
        / "pageindex-1.1.attempt-1.stderr.txt"
    ).read_text()
    assert "bad markdown" in stderr


def test_run_stage_10_uses_only_fulltext_available_promoted_papers(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1", "1.2"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "unavailable_markdown.csv").write_text(
        "arxiv_id,error_type,error\n1.1,Stage8MarkdownUnavailable,empty markdown returned for 1.1\n"
    )
    (run / "08_full_markdown" / "1.2.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.2")
    (run / "10_verified_evidence").mkdir()
    (run / "10_verified_evidence" / "1.2.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )
    monkeypatch.setattr(
        "scripts.auto_research_runner.stages.run_shards",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unavailable paper should not dispatch")),
    )

    run_stage_10(run)


def test_run_stage_10_shards_one_paper_at_a_time_and_validates_grounding(tmp_path, monkeypatch):
    run = tmp_path / "run"
    ids = ["1.1", "1.2", "1.3"]
    _write_promoted_papers(run, ids)
    (run / "08_full_markdown").mkdir(parents=True)
    for arxiv_id in ids:
        (run / "08_full_markdown" / f"{arxiv_id}.md").write_text("# Paper\n")
        _write_valid_pageindex(run, arxiv_id)
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 2]}]})
                )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_10(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [1, 1, 1]
    assert all(spec.agent == "verified_evidence_extractor" for spec in captured)
    assert all("Run Stage 10 only" in spec.prompt for spec in captured)


def test_stage_10_expected_output_repairs_malformed_json(tmp_path):
    run = tmp_path / "run"
    evidence_dir = run / "10_verified_evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "1.1.json").write_text(
        '{"claims": [{"source_node_id": "s.01", "source_lines": [1], "latex": "\\!"}]}'
    )
    spec = ShardSpec(
        stage="10",
        shard_id="verified-evidence-001",
        agent="verified_evidence_extractor",
        model="gpt-5.4-mini",
        prompt="p",
        expected_outputs=["10_verified_evidence/1.1.json"],
    )

    assert shards_mod.expected_outputs_exist(run, spec) is True
    repaired = json.loads((evidence_dir / "1.1.json").read_text())
    assert repaired["claims"][0]["latex"] == "\\!"


def test_run_stage_10_accepts_repairable_existing_evidence(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.1")
    evidence_dir = run / "10_verified_evidence"
    evidence_dir.mkdir()
    (evidence_dir / "1.1.json").write_text(
        '{"claims": [{"source_node_id": "s.01", "source_lines": [1], "latex": "\\!"}]}'
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_10(run)

    assert captured == []
    assert runner.load_verified_promoted_arxiv_ids(run) == ["1.1"]


def test_run_stage_10_retries_unrepairable_existing_evidence(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.1")
    evidence_dir = run / "10_verified_evidence"
    evidence_dir.mkdir()
    (evidence_dir / "1.1.json").write_text('{"claims": [{"source_node_id": "s.01"}]')
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        assert kwargs.get("force") is True
        (run_dir / "10_verified_evidence" / "1.1.json").write_text(
            json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
        )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_10(run)

    assert [spec.expected_outputs for spec in captured] == [["10_verified_evidence/1.1.json"]]
    assert runner.load_verified_promoted_arxiv_ids(run) == ["1.1"]


def test_run_stage_10_retries_then_quarantines_zero_claim_evidence(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1", "1.2"])
    (run / "08_full_markdown").mkdir(parents=True)
    for arxiv_id in ("1.1", "1.2"):
        (run / "08_full_markdown" / f"{arxiv_id}.md").write_text("# Paper\n")
        _write_valid_pageindex(run, arxiv_id)
    (run / "10_verified_evidence").mkdir()
    (run / "10_verified_evidence" / "1.1.json").write_text(json.dumps({"claims": []}))
    (run / "10_verified_evidence" / "1.2.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        assert kwargs.get("force") is True
        assert [spec.expected_outputs for spec in specs] == [["10_verified_evidence/1.1.json"]]
        (run_dir / "10_verified_evidence" / "1.1.json").write_text(json.dumps({"claims": []}))

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_10(run)

    assert len(captured) == 1
    assert runner.load_verified_promoted_arxiv_ids(run) == ["1.2"]
    quarantine = (run / "10_verified_evidence" / "quarantined_evidence.csv").read_text()
    assert "1.1,no_claims" in quarantine


def test_run_stage_10_retries_first_pass_zero_claim_before_quarantine(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.1")
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.append([spec.expected_outputs for spec in specs])
        assert kwargs.get("force") is True
        assert [spec.expected_outputs for spec in specs] == [["10_verified_evidence/1.1.json"]]
        (run_dir / "10_verified_evidence").mkdir(exist_ok=True)
        (run_dir / "10_verified_evidence" / "1.1.json").write_text(json.dumps({"claims": []}))

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    run_stage_10(run)

    assert calls == [
        [["10_verified_evidence/1.1.json"]],
        [["10_verified_evidence/1.1.json"]],
    ]
    quarantine = (run / "10_verified_evidence" / "quarantined_evidence.csv").read_text()
    assert "1.1,no_claims" in quarantine


def test_run_stage_10_clears_quarantine_when_evidence_becomes_valid(tmp_path):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.1")
    (run / "10_verified_evidence").mkdir()
    (run / "10_verified_evidence" / "1.1.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )
    (run / "10_verified_evidence" / "quarantined_evidence.csv").write_text(
        "arxiv_id,reason\n1.1,no_claims\n"
    )

    run_stage_10(run)

    assert runner.load_verified_promoted_arxiv_ids(run) == ["1.1"]
    quarantine_path = run / "10_verified_evidence" / "quarantined_evidence.csv"
    assert not quarantine_path.exists() or "1.1,no_claims" not in quarantine_path.read_text()


def test_load_verified_promoted_arxiv_ids_rejects_claim_outside_pageindex(tmp_path):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.1")
    (run / "10_verified_evidence").mkdir()
    (run / "10_verified_evidence" / "1.1.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.99", "source_lines": [1, 1]}]})
    )

    assert runner.load_verified_promoted_arxiv_ids(run) == []


def test_run_stage_11_validates_existing_global_graph_before_skip(tmp_path):
    run = tmp_path / "run"
    (run / "11_verified_graph").mkdir(parents=True)
    (run / "11_verified_graph" / "global_graph.json").write_text(
        json.dumps({
            "nodes": [{"id": "1.1"}],
            "edges": [{"src": "1.1", "dst": "method", "type": "USES", "confidence": "weak"}],
        })
    )
    (run / "11_verified_graph" / "graph_report.md").write_text("# Report\n")

    with pytest.raises(RuntimeError, match="confidence must be verified"):
        validation_mod.validate_verified_global_graph(run)


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


def test_run_stage_12_validates_existing_outline_before_skip(tmp_path):
    run = tmp_path / "run"
    (run / "12_taxonomy").mkdir(parents=True)
    (run / "12_taxonomy" / "outline.json").write_text(
        json.dumps({"book_sections": [], "families": [], "methods": []})
    )

    with pytest.raises(RuntimeError, match="fixed 8-section order"):
        runner.run_stage_12(run)


def test_run_stage_12_validates_fresh_outline_after_agent_run(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _write_promoted_papers(run, ["1.1"])
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "08_full_markdown" / "1.1.md").write_text("# Paper\n")
    _write_valid_pageindex(run, "1.1")
    (run / "10_verified_evidence").mkdir(parents=True)
    (run / "10_verified_evidence" / "1.1.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )

    def fake_run_shards(run_dir, specs, **kwargs):
        for relpath in specs[0].expected_outputs:
            path = run_dir / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
        (run_dir / "12_taxonomy" / "outline.json").write_text(
            json.dumps({"book_sections": [], "families": [], "methods": []})
        )

    monkeypatch.setattr("scripts.auto_research_runner.stages.run_shards", fake_run_shards)

    with pytest.raises(RuntimeError, match="fixed 8-section order"):
        runner.run_stage_12(run)


def test_build_chapter_targets_rejects_unsafe_ids(tmp_path):
    run = tmp_path / "run"
    (run / "12_taxonomy").mkdir(parents=True)
    outline = {
        "book_sections": [{"id": "../preface", "title": "Preface"}],
        "families": [],
        "methods": [],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))

    try:
        build_chapter_targets(run)
    except ValueError as error:
        assert "unsafe target id" in str(error)
    else:
        raise AssertionError("expected unsafe target id failure")


def test_run_stage_13_uses_pack_suffixes_and_stable_shard_ids(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    captured = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)

    with (
        patch("scripts.auto_research_runner.stages.build_deterministic_stage_13_packs"),
        patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards),
    ):
        run_stage_13(run)

    assert [spec.shard_id for spec in captured] == ["pack-001", "pack-002"]
    assert captured[0].expected_outputs == [
        "13_chapter_packs/book/preface_pack.json",
        "13_chapter_packs/families/fam_a_pack.json",
    ]
    assert captured[1].expected_outputs == ["13_chapter_packs/methods/m1_pack.json"]
    assert "Execute directly in this codex exec session." in captured[0].prompt
    assert "Do not spawn subagents" in captured[0].prompt
    assert "do not run nested codex commands" in captured[0].prompt
    assert '"pack_targets": ["book:preface", "family:fam_a"]' in captured[0].prompt
    assert '"pack_targets": ["method:m1"]' in captured[1].prompt

    (run / "13_chapter_packs" / "book").mkdir(parents=True)
    (run / "13_chapter_packs" / "book" / "preface_pack.json").write_text("{}")
    captured.clear()
    with (
        patch("scripts.auto_research_runner.stages.build_deterministic_stage_13_packs"),
        patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards),
    ):
        run_stage_13(run)

    assert [spec.shard_id for spec in captured] == ["pack-001", "pack-002"]
    assert captured[0].expected_outputs == [
        "13_chapter_packs/book/preface_pack.json",
        "13_chapter_packs/families/fam_a_pack.json",
    ]


def test_build_deterministic_stage_13_packs_from_verified_evidence(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)

    result = build_deterministic_stage_13_packs(run)

    assert result == {"book": 1, "families": 1, "methods": 1, "skipped": 0}
    method_pack = json.loads(
        (run / "13_chapter_packs" / "methods" / "m1_pack.json").read_text()
    )
    assert method_pack["pack_type"] == "method"
    assert method_pack["method_id"] == "m1"
    assert method_pack["arxiv_id"] == "1.1"
    assert method_pack["structured"]["equations"] == [
        {
            "latex": "x = y",
            "purpose": "core equation",
            "symbols": [],
            "source_node_id": "s.02",
            "source_lines": [3, 4],
        }
    ]
    assert [section["section_title"] for section in method_pack["section_plan"]] == [
        "Summary",
        "Motivation",
        "Intuition",
        "Theory",
        "Algorithm",
        "Example",
        "Interpretation",
        "Strengths",
        "Limitations",
        "Software",
        "Related Methods",
    ]
    sections = {
        section["section_title"]: section["source_nodes"]
        for section in method_pack["section_plan"]
    }
    for required in ("Theory", "Algorithm", "Example", "Limitations"):
        assert sections[required]
        assert sections[required][0]["section_text"].strip()
        assert sections[required][0]["arxiv_id"] == "1.1"

    family_pack = json.loads(
        (run / "13_chapter_packs" / "families" / "fam_a_pack.json").read_text()
    )
    assert family_pack["pack_type"] == "family"
    assert family_pack["method_ids"] == [
        {"id": "m1", "title": "M1", "arxiv_id": "1.1"}
    ]
    assert family_pack["comparison_rows"][0]["source_node_id"] == "s.02"
    assert family_pack["data"]["method_ids"] == [
        {"id": "m1", "title": "M1", "arxiv_id": "1.1"}
    ]
    assert family_pack["data"]["comparison_rows"][0]["source_node_id"] == "s.02"

    book_pack = json.loads(
        (run / "13_chapter_packs" / "book" / "preface_pack.json").read_text()
    )
    assert book_pack["pack_type"] == "book"
    assert book_pack["section_id"] == "preface"
    assert book_pack["data"]["topic"] == "Fixture topic"


def test_build_method_pack_scopes_knowledge_gaps_to_method_evidence(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "10_verified_evidence").mkdir(parents=True)
    (run_dir / "06_expansion").mkdir(parents=True)
    (run_dir / "10_verified_evidence" / "1234.00001.json").write_text(
        json.dumps(
            {
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
            }
        )
    )
    (run_dir / "06_expansion" / "knowledge_gap_report.json").write_text(
        json.dumps(
            {
                "knowledge_gaps": [
                    {"concept": "asr", "priority": 0.9},
                    {"concept": "mel", "priority": 0.9},
                    {"concept": "mel spectrogram", "priority": 0.9},
                    {"concept": "masked reconstruction", "priority": 0.8},
                    {"concept": "codec tokens", "priority": 0.9},
                    {"concept": "full duplex dialog", "priority": 0.9},
                    {"concept": "autoregressive decoding", "priority": 0.9},
                ]
            }
        )
    )
    outline = {
        "families": [{"id": "fam", "title": "Fam", "method_ids": ["audiomae"]}],
        "methods": [
            {
                "id": "audiomae",
                "title": "AudioMAE",
                "arxiv_id": "1234.00001",
                "family_id": "fam",
                "neighbor_method_ids": [],
            }
        ],
    }

    pack = packs_mod._build_method_pack(run_dir, outline, outline["methods"][0])

    assert pack["knowledge_gaps_to_explain"] == [
        "mel spectrogram",
        "masked reconstruction",
    ]
    assert "asr" not in pack["knowledge_gaps_to_explain"]
    assert "mel" not in pack["knowledge_gaps_to_explain"]


def test_run_stage_13_uses_deterministic_builder_before_codex_shards(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)

    with patch("scripts.auto_research_runner.stages.run_shards") as run_shards:
        run_stage_13(run)

    run_shards.assert_not_called()
    assert (run / "13_chapter_packs" / "book" / "preface_pack.json").exists()
    assert (run / "13_chapter_packs" / "families" / "fam_a_pack.json").exists()
    assert (run / "13_chapter_packs" / "methods" / "m1_pack.json").exists()


def test_build_deterministic_stage_13_reads_wrapped_pageindex_nodes(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run, wrap_nodes=True)

    build_deterministic_stage_13_packs(run)

    method_pack = json.loads(
        (run / "13_chapter_packs" / "methods" / "m1_pack.json").read_text()
    )
    theory_nodes = [
        section["source_nodes"]
        for section in method_pack["section_plan"]
        if section["section_title"] == "Theory"
    ][0]
    assert theory_nodes[0]["section_title"] == "Method"
    assert theory_nodes[0]["section_text"] == "## Method\nThe method uses x = y to update state.\n"


def test_build_deterministic_stage_13_does_not_write_invalid_method_pack(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run, omit_required_specific_sources=True)

    result = build_deterministic_stage_13_packs(run)

    assert result == {"book": 1, "families": 1, "methods": 0, "skipped": 0}
    assert not (run / "13_chapter_packs" / "methods" / "m1_pack.json").exists()


def test_build_deterministic_stage_13_falls_back_to_method_claims_for_theory_and_algorithm(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)
    evidence_path = run / "10_verified_evidence" / "1.1.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["equations"] = []
    evidence["algorithms"] = []
    evidence_path.write_text(json.dumps(evidence))

    result = build_deterministic_stage_13_packs(run)

    assert result["methods"] == 1
    method_pack = json.loads((run / "13_chapter_packs" / "methods" / "m1_pack.json").read_text())
    sections = {
        section["section_title"]: section["source_nodes"]
        for section in method_pack["section_plan"]
    }
    assert sections["Theory"][0]["node_id"] == "s.02"
    assert sections["Algorithm"][0]["node_id"] == "s.02"
    assert sections["Theory"][0]["section_text"].strip()
    assert sections["Algorithm"][0]["section_text"].strip()


def test_build_deterministic_stage_13_repairs_invalid_existing_method_pack(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)
    invalid_pack = run / "13_chapter_packs" / "methods" / "m1_pack.json"
    invalid_pack.parent.mkdir(parents=True, exist_ok=True)
    invalid_pack.write_text(
        json.dumps({"pack_type": "method", "method_id": "m1", "section_plan": []})
    )

    result = build_deterministic_stage_13_packs(run)

    assert result["methods"] == 1
    repaired = json.loads(invalid_pack.read_text())
    assert [section["section_title"] for section in repaired["section_plan"]] == [
        "Summary",
        "Motivation",
        "Intuition",
        "Theory",
        "Algorithm",
        "Example",
        "Interpretation",
        "Strengths",
        "Limitations",
        "Software",
        "Related Methods",
    ]
    assert all(
        section["source_nodes"][0]["section_text"].strip()
        for section in repaired["section_plan"]
        if section["section_title"] in {"Theory", "Algorithm", "Example", "Limitations"}
    )


def test_run_stage_14_groups_targets_by_type_and_uses_book_filenames(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        book_sections=[
            {"id": "preface", "title": "Preface"},
            {"id": "goals", "title": "Goals"},
        ],
    )
    captured = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_14(run)

    assert [(spec.shard_id, spec.agent, spec.expected_outputs) for spec in captured] == [
        (
            "write-book-001",
            "book_section_writer",
            ["14_chapters/book/00_preface.md", "14_chapters/book/03_goals.md"],
        ),
        ("write-families-001", "family_chapter_writer", ["14_chapters/families/fam_a.md"]),
        ("write-methods-001", "method_chapter_writer", ["14_chapters/methods/m1.md"]),
    ]
    assert '"section_ids": ["preface", "goals"]' in captured[0].prompt
    assert '"family_ids": ["fam_a"]' in captured[1].prompt
    assert '"method_ids": ["m1"]' in captured[2].prompt


def test_run_stage_14_shards_methods_one_at_a_time(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        methods=[
            {"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"},
            {"id": "m2", "title": "M2", "arxiv_id": "2.2", "family_id": "fam_a"},
            {"id": "m3", "title": "M3", "arxiv_id": "3.3", "family_id": "fam_a"},
        ],
    )
    captured = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_14(run)

    method_specs = [spec for spec in captured if spec.agent == "method_chapter_writer"]
    assert [(spec.shard_id, spec.expected_outputs) for spec in method_specs] == [
        ("write-methods-001", ["14_chapters/methods/m1.md"]),
        ("write-methods-002", ["14_chapters/methods/m2.md"]),
        ("write-methods-003", ["14_chapters/methods/m3.md"]),
    ]


def test_run_stage_15_writes_verification_summary_from_per_target_json(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    rows = [
        ("book", "preface", True),
        ("families", "fam_a", False),
        ("methods", "m1", True),
    ]
    for target_type, target_id, passed in rows:
        path = run / "15_verification" / target_type / f"{target_id}_verification.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "passed": passed,
                    "summary": {
                        "claims_total": 2,
                        "claims_unsupported": 0,
                        "claims_overstated": 0,
                        "gaps_covered": 1,
                        "gaps_missing": 0,
                        "word_count": 1234,
                        "form_issue_count": 0,
                        "equations_rendered": 1,
                        "pseudocode_blocks": 1,
                    },
                }
            )
        )

    with patch("scripts.auto_research_runner.stages.run_shards") as run_shards:
        run_stage_15(run)

    run_shards.assert_not_called()
    summary = (run / "15_verification" / "verification_summary.csv").read_text()
    assert "target_type,target_id,passed" in summary
    assert "book,preface,True" in summary
    assert "families,fam_a,False" in summary
    assert "methods,m1,True" in summary


def test_run_stage_15_uses_typed_chapter_targets_in_prompt(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    captured = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for relpath in spec.expected_outputs:
                path = run / relpath
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "passed": True,
                            "summary": {
                                "claims_total": 0,
                                "claims_unsupported": 0,
                                "claims_overstated": 0,
                                "gaps_covered": 0,
                                "gaps_missing": 0,
                                "word_count": 1500,
                                "form_issue_count": 0,
                                "equations_rendered": 0,
                                "pseudocode_blocks": 0,
                            },
                        }
                    )
                )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_15(run)

    assert len(captured) == 2
    assert '"chapter_targets": ["book:preface", "family:fam_a"]' in captured[0].prompt
    assert '"chapter_targets": ["method:m1"]' in captured[1].prompt


def test_run_stage_15_repairs_blocking_form_issues_once(tmp_path):
    run = tmp_path / "run"
    (run / "12_taxonomy").mkdir(parents=True)
    (run / "12_taxonomy" / "outline.json").write_text(
        json.dumps(
            {
                "topic": "Fixture topic",
                "book_sections": [{"id": "preface", "title": "Preface"}],
                "families": [],
                "methods": [],
            }
        )
    )
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend((spec.agent, spec.prompt, spec.expected_outputs) for spec in specs)
        for spec in specs:
            if spec.agent == "verifier":
                passed = len([call for call in calls if call[0] == "verifier"]) > 1
                path = run / "15_verification" / "book" / "preface_verification.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "passed": passed,
                            "form_issues": []
                            if passed
                            else [
                                {
                                    "check": "chapter_file_missing",
                                    "detail": "Missing chapter file.",
                                    "excerpt": "",
                                }
                            ],
                            "summary": {
                                "claims_total": 0,
                                "claims_unsupported": 0,
                                "claims_overstated": 0,
                                "gaps_covered": 0,
                                "gaps_missing": 0,
                                "word_count": 600 if passed else 0,
                                "form_issue_count": 0 if passed else 1,
                                "equations_rendered": 0,
                                "pseudocode_blocks": 0,
                            },
                        }
                    )
                )
            else:
                path = run / "14_chapters" / "book" / "00_preface.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Preface\n\n" + "word " * 600)

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_15(run)

    assert [call[0] for call in calls] == [
        "verifier",
        "book_section_writer",
        "verifier",
    ]
    assert '"form_issues": {"preface": [{"check": "chapter_file_missing"' in calls[1][1]
    summary = (run / "15_verification" / "verification_summary.csv").read_text()
    assert "book,preface,True" in summary


def test_run_stage_16_builds_manifest_deterministically_in_canonical_order(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        book_sections=[
            {"id": "preface", "title": "Preface"},
            {"id": "goals", "title": "Goals"},
        ],
    )
    for target in build_chapter_targets(run):
        chapter_path = run / {
            "book": f"14_chapters/book/{'00_preface.md' if target['id'] == 'preface' else '03_goals.md'}",
            "families": f"14_chapters/families/{target['id']}.md",
            "methods": f"14_chapters/methods/{target['id']}.md",
        }[target["type"]]
        chapter_path.parent.mkdir(parents=True, exist_ok=True)
        chapter_path.write_text(f"# {target['id']}\n\nBody text.\n")
        verification_path = run / "15_verification" / target["type"] / f"{target['id']}_verification.json"
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(
            json.dumps(
                {
                    "passed": True,
                    "summary": {
                        "word_count": 1500,
                        "form_issue_count": 0,
                        "equations_rendered": 0,
                        "pseudocode_blocks": 0,
                    },
                }
            )
        )

    with patch("scripts.auto_research_runner.stages.run_shards") as run_shards:
        run_stage_16(run)

    run_shards.assert_not_called()
    manifest = json.loads((run / "16_book" / "chapters_manifest.json").read_text())
    assert [chapter["chapter_id"] for chapter in manifest["chapters"]] == [
        "preface",
        "goals",
        "fam_a",
        "m1",
    ]
    assert all(chapter["status"] == "passed" for chapter in manifest["chapters"])
    assert (run / "14_chapters" / "methods" / "m1.md").read_text().startswith("---\n")
    assert not list((run / "16_book").glob("chapters_manifest_shard_*.json"))


def test_run_stage_16_treats_high_word_count_as_non_blocking(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        methods=[
            {"id": "m_long", "title": "Long Method", "arxiv_id": "1.1", "family_id": "fam_a"},
            {"id": "m_bad", "title": "Bad Method", "arxiv_id": "2.2", "family_id": "fam_a"},
        ],
    )
    verification_by_id = {
        "preface": {"passed": True, "summary": {"word_count": 600, "form_issue_count": 0}},
        "fam_a": {"passed": True, "summary": {"word_count": 1200, "form_issue_count": 0}},
        "m_long": {
            "passed": False,
            "form_issues": [
                {
                    "check": "method_word_count_high",
                    "detail": "Method chapter has 4200 words; maximum is 3000.",
                    "excerpt": "# Long Method",
                }
            ],
            "summary": {
                "word_count": 4200,
                "form_issue_count": 1,
                "claims_unsupported": 0,
                "claims_overstated": 0,
                "gaps_missing": 0,
            },
        },
        "m_bad": {
            "passed": False,
            "form_issues": [
                {
                    "check": "copied_source_outline",
                    "detail": "Copied source headings into the chapter.",
                    "excerpt": "Baselines.",
                }
            ],
            "summary": {
                "word_count": 2200,
                "form_issue_count": 1,
                "claims_unsupported": 0,
                "claims_overstated": 0,
                "gaps_missing": 0,
            },
        },
    }
    for target in build_chapter_targets(run):
        chapter_path = run / {
            "book": "14_chapters/book/00_preface.md",
            "families": f"14_chapters/families/{target['id']}.md",
            "methods": f"14_chapters/methods/{target['id']}.md",
        }[target["type"]]
        chapter_path.parent.mkdir(parents=True, exist_ok=True)
        chapter_path.write_text(f"# {target['id']}\n\nDetailed chapter body.\n")
        verification_path = run / "15_verification" / target["type"] / f"{target['id']}_verification.json"
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(json.dumps(verification_by_id[target["id"]]))

    run_stage_16(run)

    manifest = json.loads((run / "16_book" / "chapters_manifest.json").read_text())
    statuses = {chapter["chapter_id"]: chapter["status"] for chapter in manifest["chapters"]}
    assert statuses["m_long"] == "passed"
    assert statuses["m_bad"] == "excluded_form_issues"


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

    status, reason = chapters_mod._verification_status(
        target,
        verification,
        chapter_word_count=1400,
    )

    assert status == "passed"
    assert reason == ""


def test_verification_status_prefers_explicit_top_level_failed_flag():
    target = {"type": "families", "id": "evaluation_benchmarks"}
    verification = {
        "passed": False,
        "summary": {
            "passed": True,
            "claims_unsupported": 0,
            "claims_overstated": 0,
            "gaps_missing": 0,
            "form_issue_count": 0,
            "word_count": 1400,
        },
    }

    status, reason = chapters_mod._verification_status(
        target,
        verification,
        chapter_word_count=1400,
    )

    assert status == "excluded_verification_failed"
    assert reason == "verification did not pass"


def _write_outline(run, *, book_sections=None, methods=None):
    (run / "12_taxonomy").mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "Fixture topic",
        "book_sections": book_sections
        or [
            {"id": "preface", "title": "Preface"},
            {"id": "appendices", "title": "Appendices"},
        ],
        "families": [{"id": "fam_a", "title": "A", "method_ids": ["m1"]}],
        "methods": methods
        or [{"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"}],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))


def _write_stage_13_sources(run, *, wrap_nodes=False, omit_required_specific_sources=False):
    (run / "00_input").mkdir(parents=True, exist_ok=True)
    (run / "00_input" / "topic.md").write_text("# Fixture topic\n")
    (run / "06_expansion").mkdir(parents=True, exist_ok=True)
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text(
        json.dumps({"known_concepts": [{"id": "accuracy", "definition": "Correctness."}]})
    )
    (run / "06_expansion" / "knowledge_gap_report.json").write_text(
        json.dumps({"knowledge_gaps": [{"name": "latent reasoning"}]})
    )
    (run / "10_verified_evidence").mkdir(parents=True, exist_ok=True)
    (run / "10_verified_evidence" / "1.1.json").write_text(
        json.dumps(
            {
                "arxiv_id": "1.1",
                "title": "Fixture Paper",
                "year": 2026,
                "claims": [
                    {
                        "text": "The method solves the fixture problem.",
                        "source_node_id": "s.01",
                        "source_lines": [1, 2],
                        "claim_type": "motivation",
                        "confidence": "high",
                    },
                    {
                        "text": "The algorithm applies the equation to update state.",
                        "source_node_id": "s.02",
                        "source_lines": [3, 4],
                        "claim_type": "method",
                        "confidence": "high",
                    },
                ]
                + (
                    []
                    if omit_required_specific_sources
                    else [
                        {
                            "text": "The evaluation uses a small worked example.",
                            "source_node_id": "s.03",
                            "source_lines": [5, 6],
                            "claim_type": "result",
                            "confidence": "high",
                        },
                        {
                            "text": "The method is limited by noisy supervision.",
                            "source_node_id": "s.04",
                            "source_lines": [7, 8],
                            "claim_type": "limitation",
                            "confidence": "high",
                        },
                    ]
                ),
                "equations": []
                if omit_required_specific_sources
                else [
                    {
                        "latex": "x = y",
                        "purpose": "core equation",
                        "symbols": [],
                        "source_node_id": "s.02",
                        "source_lines": [3, 4],
                    }
                ],
                "algorithms": []
                if omit_required_specific_sources
                else [
                    {
                        "name": "Fixture update",
                        "pseudocode": "state <- update(state)",
                        "steps": ["Read state", "Update state", "Return state"],
                        "source_node_id": "s.02",
                        "source_lines": [3, 4],
                    }
                ],
                "hyperparameters": []
                if omit_required_specific_sources
                else [
                    {"name": "steps", "value": "3", "purpose": "depth", "source_node_id": "s.03"}
                ],
                "complexity": [
                    {"text": "Linear in sequence length.", "regime": "inference", "source_node_id": "s.02"}
                ],
                "datasets": [{"name": "FixtureSet", "source_node_id": "s.03"}],
                "limitations": []
                if omit_required_specific_sources
                else [
                    {"text": "Noisy supervision can hurt.", "source_node_id": "s.04", "source_lines": [7, 8]}
                ],
                "neighbors": [],
            }
        )
    )
    (run / "09_pageindex" / "nodes").mkdir(parents=True, exist_ok=True)
    nodes = {
        "s.01": {"id": "s.01", "title": "Introduction", "start_line": 1, "end_line": 2},
        "s.02": {"id": "s.02", "title": "Method", "start_line": 3, "end_line": 4},
        "s.03": {"id": "s.03", "title": "Experiments", "start_line": 5, "end_line": 6},
        "s.04": {"id": "s.04", "title": "Limitations", "start_line": 7, "end_line": 8},
    }
    if wrap_nodes:
        nodes_payload = {"arxiv_id": "1.1", "nodes": nodes}
    else:
        nodes_payload = nodes
    (run / "09_pageindex" / "nodes" / "1.1.nodes.json").write_text(
        json.dumps(nodes_payload)
    )
    (run / "08_full_markdown").mkdir(parents=True, exist_ok=True)
    (run / "08_full_markdown" / "1.1.md").write_text(
        "\n".join(
            [
                "## Introduction",
                "The fixture problem motivates the method.",
                "## Method",
                "The method uses x = y to update state.",
                "## Experiments",
                "A worked example uses three update steps.",
                "## Limitations",
                "Noisy supervision can hurt the method.",
            ]
        )
        + "\n"
    )


def _skip_stage_1_start_preflight(monkeypatch):
    monkeypatch.setattr(
        "scripts.auto_research_runner.cli._validate_stage_1_before_later_start",
        lambda run_dir, start: None,
    )


def test_main_resume_from_stage_11_calls_stage_11(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    def fake_stage(run_dir):
        calls.append(run_dir.name)

    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_11", fake_stage)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_13", lambda run_dir: None)

    rc = main(["--run-id", "demo", "--phase", "draft", "--resume", "--from-stage", "11"])

    assert rc == 0
    assert calls == ["demo"]


def test_main_all_resume_from_stage_7_includes_bootstrap_handlers(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_7", lambda run_dir: calls.append("7"))
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_8", lambda run_dir: calls.append("8"))
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_9", lambda run_dir: calls.append("9"))
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_10", lambda run_dir: calls.append("10"))
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_11", lambda run_dir: calls.append("11"))
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_13", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_14", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_15", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_16", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_17", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_18", lambda run_dir: None)

    rc = main(["--run-id", "demo", "--phase", "all", "--resume", "--from-stage", "7"])

    assert rc == 0
    assert calls[:5] == ["7", "8", "9", "10", "11"]


def test_main_resume_from_stage_7_validates_stage_1_keep_all_contract(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    _write_valid_bootstrap_contract(run)
    kept_ids = [f"2501.{idx:05d}" for idx in range(200)]
    selected_ids = kept_ids[:50]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps(
            [{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in selected_ids]
        )
    )
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    calls = []
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_7", lambda run_dir: calls.append("7"))

    with pytest.raises(RuntimeError, match="paper_pool.json must contain every paper kept"):
        main(["--run-id", "demo", "--phase", "all", "--resume", "--from-stage", "7"])

    assert calls == []


def test_main_rejects_from_stage_outside_phase(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")

    try:
        main(["--run-id", "demo", "--phase", "draft", "--resume", "--from-stage", "14"])
    except SystemExit as error:
        assert "stage 14 is not available for phase draft" in str(error)
    else:
        raise AssertionError("expected invalid from-stage failure")


def test_main_write_phase_defaults_to_stage_14(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    for stage in ("14", "15", "16", "17", "18"):
        monkeypatch.setattr(
            f"scripts.auto_research_runner.cli.run_stage_{stage}",
            lambda run_dir, stage=stage: calls.append(stage),
        )

    rc = main(["--run-id", "demo", "--phase", "write"])

    assert rc == 0
    assert calls == ["14", "15", "16", "17", "18"]


def test_main_write_phase_uses_stage_worker_caps(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.delenv("SWARN_MAX_EFFECTIVE_WORKERS", raising=False)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    def fake_parallel_stage(run_dir, *, max_workers=1):
        calls.append(max_workers)

    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_14", fake_parallel_stage)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_15", fake_parallel_stage)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_16", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_17", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_18", lambda run_dir: None)

    rc = main(["--run-id", "demo", "--phase", "write", "--max-workers", "20"])

    assert rc == 0
    assert calls == [10, 5]


def test_main_uses_stage_6_specific_worker_cap(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.delenv("SWARN_MAX_EFFECTIVE_WORKERS", raising=False)
    monkeypatch.delenv("SWARN_STAGE_6_MAX_EFFECTIVE_WORKERS", raising=False)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    def fake_stage(stage):
        def inner(run_dir, *, max_workers=1, executor="sdk-cli-fallback"):
            calls.append((stage, max_workers))

        return inner

    for stage in (
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "12.5",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ):
        monkeypatch.setattr(
            f"scripts.auto_research_runner.cli.run_stage_{stage.replace('.', '_')}",
            fake_stage(stage),
        )

    rc = main(["--run-id", "demo", "--phase", "all", "--resume", "--from-stage", "6", "--max-workers", "20"])

    assert rc == 0
    assert calls[0:5] == [("6", 10), ("7", 20), ("8", 20), ("9", 20), ("10", 20)]


def test_main_cleans_research_mcp_processes_after_stage_6(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    cleanup_calls = []

    def fake_stage(stage):
        def inner(run_dir, *, max_workers=1, executor="sdk-cli-fallback"):
            cleanup_calls.append(("stage", stage))

        return inner

    for stage in (
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "12.5",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ):
        monkeypatch.setattr(
            f"scripts.auto_research_runner.cli.run_stage_{stage.replace('.', '_')}",
            fake_stage(stage),
        )
    monkeypatch.setattr(
        "scripts.auto_research_runner.cli.cleanup_stage_6_research_mcp_processes",
        lambda run_dir: cleanup_calls.append(("cleanup", "mcp")),
    )

    rc = main(["--run-id", "demo", "--phase", "all", "--resume", "--from-stage", "6"])

    assert rc == 0
    assert cleanup_calls[:3] == [
        ("stage", "6"),
        ("cleanup", "mcp"),
        ("stage", "7"),
    ]
    assert cleanup_calls.count(("cleanup", "mcp")) == 1


def test_main_write_phase_rejects_draft_from_stage(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")

    try:
        main(["--run-id", "demo", "--phase", "write", "--from-stage", "11"])
    except SystemExit as error:
        assert "stage 11 is not available for phase write" in str(error)
    else:
        raise AssertionError("expected invalid write from-stage failure")


def test_main_write_phase_rejects_saved_draft_current_stage(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "draft",
            "topic": "Old topic",
            "status": "running",
            "current_stage": "11",
        },
    )

    try:
        main(["--run-id", "demo", "--phase", "write", "--resume"])
    except SystemExit as error:
        assert "stage 11 is not available for phase write" in str(error)
    else:
        raise AssertionError("expected saved draft current_stage failure")


def test_main_with_topic_starts_new_run_before_requested_stage(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)

    def fake_start_run(topic, phase):
        run = tmp_path / "research_runs" / "demo-run"
        run.mkdir(parents=True)
        return "demo-run"

    monkeypatch.setattr("scripts.auto_research_runner.cli.start_new_run", fake_start_run)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_11", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.auto_research_runner.cli.run_stage_13", lambda run_dir: None)

    rc = main(["--topic", "Demo topic", "--phase", "draft", "--from-stage", "11"])

    assert rc == 0
    assert (tmp_path / "research_runs" / "demo-run" / "run_control" / "run_state.json").exists()


def test_main_topic_all_uses_stage_scoped_bootstrap_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
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

    monkeypatch.setattr("scripts.auto_research_runner.cli.start_new_run", fake_start_run)
    for stage in (
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "12.5",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ):
        monkeypatch.setattr(
            f"scripts.auto_research_runner.cli.run_stage_{stage.replace('.', '_')}",
            fake_stage(stage),
        )

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


def _write_valid_bootstrap_contract(run, ids=None):
    if ids is None:
        ids = [f"2501.{idx:05d}" for idx in range(200)]
    (run / "00_input").mkdir(parents=True)
    (run / "01_seed_pool").mkdir(parents=True)
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "04_weak_evidence").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "09_pageindex" / "trees").mkdir(parents=True)
    (run / "09_pageindex" / "nodes").mkdir(parents=True)
    (run / "10_verified_evidence").mkdir(parents=True)

    aspects = [
        {
            "id": f"aspect_{idx}",
            "normal_queries": [f"normal query {idx}"],
            "survey_queries": ([f"survey query {idx}"] if idx < 3 else []),
            "positive_keywords": [f"keyword {idx}"],
        }
        for idx in range(4)
    ]
    (run / "00_input" / "search_plan.json").write_text(
        json.dumps({"aspects": aspects})
    )
    bulk_path = run / "01_seed_pool" / "bulk_search_results_123.json"
    bulk_path.write_text(json.dumps({arxiv_id: "abstract" for arxiv_id in ids}))
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": {arxiv_id: "abstract" for arxiv_id in ids},
                "total_kept": len(ids),
                "output_path": str(bulk_path),
            }
        )
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in ids])
    )
    (run / "02_paper_pool" / "paper_pool.csv").write_text(
        "arxiv_id\n" + "\n".join(ids) + "\n"
    )
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
    for arxiv_id in ids:
        (run / "04_weak_evidence" / f"{arxiv_id}.json").write_text(
            json.dumps({"reader_needed_concepts": ["concept"]})
        )
    promoted_id = ids[0]
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
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": promoted_id, "final_score": 0.9}]})
    )
    (run / "08_full_markdown" / f"{promoted_id}.md").write_text("# Paper\n")
    (run / "09_pageindex" / "trees" / f"{promoted_id}.tree.json").write_text(
        json.dumps(
            {
                "arxiv_id": promoted_id,
                "root": {
                    "id": "s.00",
                    "title": "(root)",
                    "children": [
                        {
                            "id": "s.01",
                            "title": "Paper",
                            "level": 1,
                            "start_line": 1,
                            "end_line": 1,
                            "parent_id": "s.00",
                            "summary": "Paper.",
                            "children": [],
                        }
                    ],
                },
            }
        )
    )
    (run / "09_pageindex" / "nodes" / f"{promoted_id}.nodes.json").write_text(
        json.dumps(
            {
                "s.01": {
                    "id": "s.01",
                    "title": "Paper",
                    "level": 1,
                    "start_line": 1,
                    "end_line": 1,
                    "parent_id": "s.00",
                    "summary": "Paper.",
                }
            }
        )
    )
    (run / "10_verified_evidence" / f"{promoted_id}.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )


def test_validate_bootstrap_contract_requires_real_bulk_search_artifact(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps({"papers": {"2501.00000": "abstract"}})
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "output_path" in str(error)
    else:
        raise AssertionError("expected missing bulk output_path failure")


def test_validate_bootstrap_contract_rejects_too_many_search_aspects(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    aspects = [
        {
            "id": f"aspect_{idx}",
            "normal_queries": [f"normal query {idx}"],
            "survey_queries": ([f"survey query {idx}"] if idx < 3 else []),
            "positive_keywords": [f"keyword {idx}"],
        }
        for idx in range(6)
    ]
    (run / "00_input" / "search_plan.json").write_text(json.dumps({"aspects": aspects}))

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "4..5 aspects" in str(error)
    else:
        raise AssertionError("expected too many aspects failure")


def test_validate_bootstrap_contract_rejects_tiny_paper_pool(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    tiny_ids = [f"2501.{idx:05d}" for idx in range(3)]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in tiny_ids])
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "at least 40 papers" in str(error)
    else:
        raise AssertionError("expected tiny paper pool failure")


def test_validate_bootstrap_contract_rejects_truncated_large_seed_pool(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    kept_ids = [f"2501.{idx:05d}" for idx in range(220)]
    selected_ids = kept_ids[:50]
    (run / "01_seed_pool" / "bulk_search_results_123.json").write_text(
        json.dumps({arxiv_id: "abstract" for arxiv_id in kept_ids})
    )
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": {arxiv_id: "abstract" for arxiv_id in kept_ids},
                "total_kept": len(kept_ids),
                "output_path": str(run / "01_seed_pool" / "bulk_search_results_123.json"),
            }
        )
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in selected_ids])
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(kept_ids),
                "target_seed_papers": 200,
                "selected_total": len(selected_ids),
                "per_aspect_selected": {f"aspect_{idx}": 10 for idx in range(4)},
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_pool.json must contain every paper kept by bulk search" in str(error)
    else:
        raise AssertionError("expected truncated large seed pool failure")


def test_validate_bootstrap_contract_requires_candidate_pool_report(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    (run / "02_paper_pool" / "candidate_pool_report.json").unlink()

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "candidate_pool_report.json" in str(error)
    else:
        raise AssertionError("expected missing candidate pool report failure")


def test_validate_bootstrap_contract_accepts_real_discovery_shape(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)

    validate_bootstrap_stage_0_10_contract(run)


def test_validate_stage_1_keep_all_contract_requires_pool_csv_matches_json(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    csv_ids = ids[:-1] + ["2502.99999"]
    (run / "02_paper_pool" / "paper_pool.csv").write_text(
        "arxiv_id\n" + "\n".join(csv_ids) + "\n"
    )

    with pytest.raises(RuntimeError) as error:
        validate_stage_1_keep_all_contract(run)

    assert "paper_pool.csv must contain exactly every paper_pool arxiv_id" in str(error.value)


def test_validate_stage_1_keep_all_contract_rejects_bulk_output_mismatch(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    (run / "01_seed_pool" / "bulk_search_results_123.json").write_text(
        json.dumps({arxiv_id: "abstract" for arxiv_id in ids + ["2502.99999"]})
    )

    with pytest.raises(RuntimeError) as error:
        validate_stage_1_keep_all_contract(run)

    assert "bulk_search_results artifact must match seed_pool_raw.json papers" in str(error.value)


def test_validate_stage_1_keep_all_contract_requires_query_fields_per_aspect(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    search_plan_path = run / "00_input" / "search_plan.json"
    search_plan = json.loads(search_plan_path.read_text())
    search_plan["aspects"][0]["normal_queries"] = []
    search_plan_path.write_text(json.dumps(search_plan))

    with pytest.raises(RuntimeError) as error:
        validate_stage_1_keep_all_contract(run)

    assert "must include non-empty normal_queries and positive_keywords" in str(error.value)


def test_validate_bootstrap_contract_rejects_duplicate_raw_seed_ids(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    duplicate_raw_ids = ids + [ids[0]]
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": duplicate_raw_ids,
                "total_kept": len(duplicate_raw_ids),
                "output_path": str(run / "01_seed_pool" / "bulk_search_results_123.json"),
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "seed_pool_raw.json papers must not contain duplicate arxiv_id" in str(error)
    else:
        raise AssertionError("expected duplicate raw seed failure")


def test_validate_bootstrap_contract_rejects_duplicate_paper_pool_ids(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    duplicate_pool_ids = ids + [ids[0]]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps(
            [
                {"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"}
                for arxiv_id in duplicate_pool_ids
            ]
        )
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(ids),
                "selected_total": len(duplicate_pool_ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_pool.json must not contain duplicate arxiv_id" in str(error)
    else:
        raise AssertionError("expected duplicate paper pool failure")


def test_validate_bootstrap_contract_ignores_legacy_target_seed_papers(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(60)]
    _write_valid_bootstrap_contract(run, ids=ids)
    search_plan = json.loads((run / "00_input" / "search_plan.json").read_text())
    search_plan["target_seed_papers"] = 40
    (run / "00_input" / "search_plan.json").write_text(json.dumps(search_plan))

    validate_bootstrap_stage_0_10_contract(run)


def test_validate_bootstrap_contract_rejects_missing_raw_seed_paper(tmp_path):
    run = tmp_path / "run"
    raw_ids = [f"2501.{idx:05d}" for idx in range(60)]
    selected_ids = raw_ids[:-1] + ["2502.99999"]
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


def test_bootstrap_new_run_is_retired():
    try:
        bootstrap_new_run("Demo topic", "all")
    except RuntimeError as error:
        assert "retired" in str(error)
    else:
        raise AssertionError("expected retired bootstrap failure")


def test_main_status_reports_failed_sdk_thread(tmp_path, monkeypatch, capsys):
    run = tmp_path / "research_runs" / "demo"
    shard_dir = run / "run_control" / "stages" / "14" / "shards"
    shard_dir.mkdir(parents=True)
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "write",
            "status": "failed",
            "current_stage": "14",
        },
    )
    (run / "run_log.csv").write_text(
        "timestamp,stage,status,detail\n2026-01-01T00:00:00+00:00,14,failed,write-001 missing expected outputs\n"
    )
    (shard_dir / "write-001.attempt-1.stderr.txt").write_text("bad chapter\n")
    (shard_dir / "write-001.json").write_text(
        json.dumps(
            {
                "stage": "14",
                "shard_id": "write-001",
                "status": "failed",
                "executor": "sdk",
                "thread_id": "thread-123",
                "turn_id": "turn-456",
                "stderr_path": "run_control/stages/14/shards/write-001.attempt-1.stderr.txt",
            }
        )
    )

    rc = main(["--run-id", "demo", "--status"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "run_id=demo" in out
    assert "status=failed" in out
    assert "failed_stage=14" in out
    assert "failed_shard=write-001" in out
    assert "thread_id=thread-123" in out
    assert "turn_id=turn-456" in out
    assert "stderr=run_control/stages/14/shards/write-001.attempt-1.stderr.txt" in out


def test_status_reports_latest_shard_after_recovery(tmp_path):
    run = tmp_path / "run"
    shard_dir = run / "run_control" / "stages" / "8" / "shards"
    shard_dir.mkdir(parents=True)
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "all",
            "status": "paused",
            "current_stage": "9",
            "last_completed_stage": "8",
        },
    )
    failed_path = shard_dir / "old-failed.json"
    failed_path.write_text(
        json.dumps({"stage": "8", "shard_id": "old-failed", "status": "failed"})
    )
    completed_path = shard_dir / "new-completed.json"
    completed_path.write_text(
        json.dumps({"stage": "8", "shard_id": "new-completed", "status": "completed"})
    )
    os.utime(failed_path, (100, 100))
    os.utime(completed_path, (200, 200))

    out = cli_mod.format_run_status(run)

    assert "latest_shard=new-completed" in out
    assert "failed_shard=old-failed" not in out


def test_main_rejects_topic_write_phase():
    try:
        main(["--topic", "Demo topic", "--phase", "write"])
    except SystemExit as error:
        assert "--topic cannot be used with --phase write" in str(error)
    else:
        raise AssertionError("expected topic write phase failure")


def test_main_rejects_unsafe_cli_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.auto_research_runner.cli.RUNS_ROOT", tmp_path / "research_runs")

    try:
        main(["--run-id", "../escape", "--phase", "draft"])
    except ValueError as error:
        assert "unsafe run_id" in str(error)
    else:
        raise AssertionError("expected unsafe CLI run_id failure")
