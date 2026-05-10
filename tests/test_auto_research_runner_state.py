from __future__ import annotations

import csv
import json

import scripts.run_auto_research as runner
from scripts.run_auto_research import (
    append_run_log,
    ensure_run_control,
    load_run_state,
    main,
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
    assert primary_artifact_exists(run, "11") is False

    (run / "11_verified_graph" / "graph_report.md").write_text("Graph report\n")
    assert primary_artifact_exists(run, "11") is True


def test_main_preserves_existing_resume_state(tmp_path, monkeypatch):
    runs_root = tmp_path / "research_runs"
    run = runs_root / "demo"
    monkeypatch.setattr(runner, "RUNS_ROOT", runs_root)
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
    assert state["current_stage"] == "11"
    assert state["last_completed_stage"] == "10"
    assert state["status"] == "ready"
    assert state["resume"] is True
