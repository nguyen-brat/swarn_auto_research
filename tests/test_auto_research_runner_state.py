from __future__ import annotations

import csv
import importlib
import json
from types import SimpleNamespace

import scripts.auto_research_runner.cli as cli_mod
import scripts.auto_research_runner.shards as shards_mod
from scripts.auto_research_runner.cli import main
from scripts.auto_research_runner.config import (
    BOOTSTRAP_TIMEOUT_SECONDS,
    DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS,
    DEFAULT_STAGE_SDK_NOTIFICATION_TIMEOUT_SECONDS,
)
from scripts.auto_research_runner.shards import (
    _run_sdk_prompt,
    _run_shard_attempt,
)
from scripts.auto_research_runner.shared_types import (
    ShardAttemptResult,
    ShardSpec,
)
from scripts.auto_research_runner.state import (
    append_run_log,
    ensure_run_control,
    load_run_state,
    save_run_state,
)
from scripts.auto_research_runner.validation import primary_artifact_exists


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


def test_internal_modules_expose_shared_types_and_state():
    shared_types = importlib.import_module("scripts.auto_research_runner.shared_types")
    state = importlib.import_module("scripts.auto_research_runner.state")
    artifacts = importlib.import_module("scripts.auto_research_runner.artifacts")

    assert hasattr(shared_types, "ShardSpec")
    assert hasattr(shared_types, "ShardAttemptResult")
    assert hasattr(shared_types, "Stage8MarkdownUnavailable")
    assert hasattr(state, "load_run_state")
    assert hasattr(state, "save_run_state")
    assert hasattr(artifacts, "_build_pageindex_for_paper")
    assert hasattr(artifacts, "run_stage_11_merge")


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
    assert primary_artifact_exists(run, "11") is False

    (run / "11_verified_graph" / "graph_report.md").write_text("Graph report\n")
    assert primary_artifact_exists(run, "11") is True


def test_primary_artifact_exists_for_stage_19(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    (run / "19_handbook" / ".validated").mkdir(parents=True)
    assert primary_artifact_exists(run, "19") is False

    (run / "19_handbook" / ".validated" / "build-ok.json").write_text("{}")
    assert primary_artifact_exists(run, "19") is True


def test_main_preserves_existing_resume_state(tmp_path, monkeypatch):
    runs_root = tmp_path / "research_runs"
    run = runs_root / "demo"
    monkeypatch.setattr(cli_mod, "RUNS_ROOT", runs_root)
    calls = []
    _patch_stage_handlers(monkeypatch, calls)
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "draft",
            "topic": "Old topic",
            "status": "running",
            "current_stage": "11",
            "last_completed_stage": "10",
        },
    )

    assert main(["--run-id", "demo", "--phase", "all", "--resume"]) == 0

    state = load_run_state(run)
    assert state["topic"] == "Old topic"
    assert state["current_stage"] == "19"
    assert state["last_completed_stage"] == "19"
    assert state["status"] == "completed"
    assert state["resume"] is True
    assert calls == ["11", "12", "12.5", "13", "14", "15", "16", "17", "18", "19"]


def test_main_resume_saved_later_stage_validates_stage_1_before_handlers(tmp_path, monkeypatch):
    runs_root = tmp_path / "research_runs"
    run = runs_root / "demo"
    monkeypatch.setattr(cli_mod, "RUNS_ROOT", runs_root)
    calls = []
    monkeypatch.setattr(cli_mod, "run_stage_11", lambda run_dir: calls.append("11"))
    monkeypatch.setattr(
        cli_mod,
        "validate_stage_1_keep_all_contract",
        lambda run_dir: (_ for _ in ()).throw(RuntimeError("stage 1 invalid")),
    )
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "draft",
            "topic": "Old topic",
            "status": "running",
            "current_stage": "11",
            "last_completed_stage": "10",
        },
    )

    try:
        main(["--run-id", "demo", "--phase", "all", "--resume"])
    except RuntimeError as error:
        assert "stage 1 invalid" in str(error)
    else:
        raise AssertionError("expected Stage 1 preflight failure")

    state = load_run_state(run)
    assert state["status"] == "failed"
    assert state["failed_stage"] == "11"
    assert state["error_type"] == "RuntimeError"
    assert state["error"] == "stage 1 invalid"
    assert calls == []


def test_main_marks_state_failed_when_stage_handler_raises(tmp_path, monkeypatch, capsys):
    runs_root = tmp_path / "research_runs"
    run = runs_root / "demo"
    monkeypatch.setattr(cli_mod, "RUNS_ROOT", runs_root)
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "draft",
            "topic": "Old topic",
            "status": "running",
            "current_stage": "11",
            "last_completed_stage": "10",
        },
    )
    monkeypatch.setattr(
        cli_mod,
        "_validate_stage_1_before_later_start",
        lambda run_dir, start: None,
    )

    def fail_stage(_run_dir):
        raise RuntimeError("stage exploded")

    monkeypatch.setattr(cli_mod, "run_stage_11", fail_stage)

    try:
        main(["--run-id", "demo", "--phase", "all", "--resume"])
    except RuntimeError as error:
        assert "stage exploded" in str(error)
    else:
        raise AssertionError("expected stage failure")

    state = load_run_state(run)
    assert state["status"] == "failed"
    assert state["current_stage"] == "11"
    assert state["failed_stage"] == "11"
    assert state["last_completed_stage"] == "10"
    assert state["error_type"] == "RuntimeError"
    assert state["error"] == "stage exploded"

    with (run / "run_log.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["stage"] == "11"
    assert rows[-1]["status"] == "failed"
    assert "stage exploded" in rows[-1]["detail"]

    assert main(["--run-id", "demo", "--status"]) == 0
    out = capsys.readouterr().out
    assert "status=failed" in out
    assert "failed_stage=11" in out
    assert "error_type=RuntimeError" in out
    assert "error=stage exploded" in out


def test_main_records_keyboard_interrupt_as_interrupted(tmp_path, monkeypatch, capsys):
    runs_root = tmp_path / "research_runs"
    run = runs_root / "demo"
    monkeypatch.setattr(cli_mod, "RUNS_ROOT", runs_root)
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "draft",
            "topic": "Old topic",
            "status": "running",
            "current_stage": "11",
            "last_completed_stage": "10",
        },
    )
    monkeypatch.setattr(
        cli_mod,
        "_validate_stage_1_before_later_start",
        lambda run_dir, start: None,
    )

    def interrupt_stage(_run_dir):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_mod, "run_stage_11", interrupt_stage)

    try:
        main(["--run-id", "demo", "--phase", "all", "--resume"])
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("expected keyboard interrupt")

    state = load_run_state(run)
    assert state["status"] == "interrupted"
    assert state["current_stage"] == "11"
    assert state["failed_stage"] == "11"
    assert state["error_type"] == "KeyboardInterrupt"

    with (run / "run_log.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["stage"] == "11"
    assert rows[-1]["status"] == "interrupted"
    assert "KeyboardInterrupt" in rows[-1]["detail"]

    assert main(["--run-id", "demo", "--status"]) == 0
    out = capsys.readouterr().out
    assert "status=interrupted" in out
    assert "failed_stage=11" in out
    assert "error_type=KeyboardInterrupt" in out


def test_sdk_cli_fallback_uses_cli_when_sdk_notifications_timeout(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    spec = ShardSpec(
        stage="1",
        shard_id="query-planner",
        agent="query_planner",
        model="gpt-5.4-mini",
        prompt="write search plan",
        expected_outputs=["00_input/search_plan.json"],
    )
    calls = []

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("sdk")
        raise TimeoutError("Timed out waiting for app-server message after 51.409s")

    def pass_cli(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("cli")
        return ShardAttemptResult(
            returncode=0,
            stdout="ok",
            stderr="",
            executor="cli",
        )

    monkeypatch.setattr(shards_mod, "_run_sdk_shard_attempt", fail_sdk)
    monkeypatch.setattr(shards_mod, "_run_cli_shard_attempt_until_outputs", pass_cli)

    result = _run_shard_attempt(
        run,
        spec,
        timeout_seconds=60,
        executor="sdk-cli-fallback",
    )

    assert calls == ["sdk", "cli"]
    assert result.returncode == 0
    assert result.executor == "cli"
    assert "SDK executor timed out" in result.stderr


def test_sdk_cli_fallback_accepts_existing_outputs_after_sdk_timeout(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    (run / "00_input").mkdir(parents=True)
    (run / "00_input" / "search_plan.json").write_text("{}", encoding="utf-8")
    spec = ShardSpec(
        stage="1",
        shard_id="query-planner",
        agent="query_planner",
        model="gpt-5.4-mini",
        prompt="write search plan",
        expected_outputs=["00_input/search_plan.json"],
    )
    calls = []

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("sdk")
        raise TimeoutError("Timed out waiting for app-server message after 51.409s")

    def fail_cli(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("cli")
        raise AssertionError("CLI fallback should not run when outputs already exist")

    monkeypatch.setattr(shards_mod, "_run_sdk_shard_attempt", fail_sdk)
    monkeypatch.setattr(shards_mod, "_run_cli_shard_attempt_until_outputs", fail_cli)

    result = _run_shard_attempt(
        run,
        spec,
        timeout_seconds=60,
        executor="sdk-cli-fallback",
    )

    assert calls == ["sdk"]
    assert result.returncode == 0
    assert result.executor == "sdk"
    assert "SDK executor timed out after producing expected outputs" in result.stderr


def test_run_sdk_prompt_uses_bounded_notification_timeout(monkeypatch):
    import sdk.codex as codex_module

    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(thread_id="thread-1", turn_id="turn-1", final_response="ok")

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)
    monkeypatch.setenv("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS", "123")

    result = _run_sdk_prompt(
        "write search plan",
        model="gpt-5.4-mini",
        timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
    )

    assert result.final_response == "ok"
    assert observed["timeout"] == float(BOOTSTRAP_TIMEOUT_SECONDS)
    assert observed["notification_timeout"] == 123.0


def test_run_sdk_prompt_defaults_to_fifteen_minute_notification_timeout(monkeypatch):
    import sdk.codex as codex_module

    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(thread_id="thread-1", turn_id="turn-1", final_response="ok")

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)
    monkeypatch.delenv("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS", raising=False)

    result = _run_sdk_prompt(
        "write search plan",
        model="gpt-5.4-mini",
        timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
    )

    assert result.final_response == "ok"
    assert DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS == 900
    assert observed["notification_timeout"] == 900.0


def test_run_sdk_prompt_uses_stage_11_notification_timeout(monkeypatch):
    import sdk.codex as codex_module

    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(thread_id="thread-1", turn_id="turn-1", final_response="ok")

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)
    monkeypatch.delenv("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SWARN_STAGE_11_SDK_NOTIFICATION_TIMEOUT_SECONDS", raising=False)

    result = _run_sdk_prompt(
        "write verified graph fragment",
        model="gpt-5.4-mini",
        timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
        stage="11",
    )

    assert result.final_response == "ok"
    assert DEFAULT_STAGE_SDK_NOTIFICATION_TIMEOUT_SECONDS["11"] == 300
    assert observed["notification_timeout"] == 300.0


def test_run_sdk_prompt_uses_stage_19_notification_timeout(monkeypatch):
    import sdk.codex as codex_module

    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(thread_id="thread-1", turn_id="turn-1", final_response="ok")

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)
    monkeypatch.delenv("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SWARN_STAGE_19_SDK_NOTIFICATION_TIMEOUT_SECONDS", raising=False)

    result = _run_sdk_prompt(
        "write handbook scaffold",
        model="gpt-5.4",
        timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
        stage="19",
    )

    assert result.final_response == "ok"
    assert DEFAULT_STAGE_SDK_NOTIFICATION_TIMEOUT_SECONDS["19"] == 300
    assert observed["notification_timeout"] == 300.0


def test_run_sdk_prompt_uses_stage_specific_env_notification_timeout(monkeypatch):
    import sdk.codex as codex_module

    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(thread_id="thread-1", turn_id="turn-1", final_response="ok")

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)
    monkeypatch.setenv("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("SWARN_STAGE_11_SDK_NOTIFICATION_TIMEOUT_SECONDS", "222")

    result = _run_sdk_prompt(
        "write verified graph fragment",
        model="gpt-5.4-mini",
        timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
        stage="11",
    )

    assert result.final_response == "ok"
    assert observed["notification_timeout"] == 222.0


def test_main_resets_progress_without_resume(tmp_path, monkeypatch):
    runs_root = tmp_path / "research_runs"
    run = runs_root / "demo"
    monkeypatch.setattr(cli_mod, "RUNS_ROOT", runs_root)
    calls = []
    _patch_stage_handlers(monkeypatch, calls)
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "draft",
            "topic": "Old topic",
            "status": "running",
            "current_stage": "15",
            "last_completed_stage": "14",
        },
    )

    assert main(["--run-id", "demo", "--topic", "New topic", "--phase", "all"]) == 0

    state = load_run_state(run)
    assert state["topic"] == "New topic"
    assert state["current_stage"] == "19"
    assert state["last_completed_stage"] == "19"
    assert state["status"] == "completed"
    assert state["resume"] is False
    assert calls == ["11", "12", "12.5", "13", "14", "15", "16", "17", "18", "19"]


def _patch_stage_handlers(monkeypatch, calls):
    monkeypatch.setattr(
        cli_mod,
        "_validate_stage_1_before_later_start",
        lambda run_dir, start: None,
    )
    for stage, name in (
        ("11", "run_stage_11"),
        ("12", "run_stage_12"),
        ("12.5", "run_stage_12_5"),
        ("13", "run_stage_13"),
        ("14", "run_stage_14"),
        ("15", "run_stage_15"),
        ("16", "run_stage_16"),
        ("17", "run_stage_17"),
        ("18", "run_stage_18"),
        ("19", "run_stage_19"),
    ):
        monkeypatch.setattr(cli_mod, name, lambda run_dir, stage=stage: calls.append(stage))
