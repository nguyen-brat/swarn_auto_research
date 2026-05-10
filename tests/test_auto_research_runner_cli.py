from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.run_auto_research import (
    bootstrap_new_run,
    build_chapter_targets,
    main,
    run_deterministic_command,
    run_stage_13,
    run_stage_14,
    run_stage_15,
    run_stage_16,
    run_stage_18,
    save_run_state,
)


def test_run_deterministic_command_logs_failure(tmp_path):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    completed = type(
        "Completed",
        (),
        {"returncode": 2, "stdout": "bad stdout", "stderr": "bad stderr"},
    )()

    with patch("scripts.run_auto_research.subprocess.run", return_value=completed):
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
        "scripts.run_auto_research.subprocess.run",
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

    with patch("scripts.run_auto_research.run_deterministic_command") as command:
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

    def fake_run_shards(run_dir, specs, max_retries=1):
        captured.extend(specs)

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_13(run)

    assert [spec.shard_id for spec in captured] == ["pack-001", "pack-002", "pack-003"]
    assert captured[0].expected_outputs == ["13_chapter_packs/book/preface_pack.json"]
    assert captured[1].expected_outputs == ["13_chapter_packs/families/fam_a_pack.json"]
    assert captured[2].expected_outputs == ["13_chapter_packs/methods/m1_pack.json"]

    (run / "13_chapter_packs" / "book").mkdir(parents=True)
    (run / "13_chapter_packs" / "book" / "preface_pack.json").write_text("{}")
    captured.clear()
    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_13(run)

    assert [spec.shard_id for spec in captured] == ["pack-002", "pack-003"]


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

    def fake_run_shards(run_dir, specs, max_retries=1):
        captured.extend(specs)

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
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

    with patch("scripts.run_auto_research.run_shards") as run_shards:
        run_stage_15(run)

    run_shards.assert_not_called()
    summary = (run / "15_verification" / "verification_summary.csv").read_text()
    assert "target_type,target_id,passed" in summary
    assert "book,preface,True" in summary
    assert "families,fam_a,False" in summary
    assert "methods,m1,True" in summary


def test_run_stage_16_merges_manifest_shards_in_canonical_order(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        book_sections=[
            {"id": "preface", "title": "Preface"},
            {"id": "goals", "title": "Goals"},
        ],
    )

    def fake_run_shards(run_dir, specs, max_retries=1):
        for spec in specs:
            path = run_dir / spec.expected_outputs[0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    [
                        {
                            "chapter_id": target["id"],
                            "chapter_type": target["type"],
                            "file": f"dummy/{target['id']}.md",
                        }
                        for target in json.loads(spec.prompt.split("payload=", 1)[1].split("\n", 1)[0])["targets"]
                    ]
                )
            )

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_16(run)

    manifest = json.loads((run / "16_book" / "chapters_manifest.json").read_text())
    assert [chapter["chapter_id"] for chapter in manifest["chapters"]] == [
        "preface",
        "goals",
        "fam_a",
        "m1",
    ]
    assert not list((run / "16_book").glob("chapters_manifest_shard_*.json"))


def _write_outline(run, *, book_sections=None):
    (run / "12_taxonomy").mkdir(parents=True, exist_ok=True)
    outline = {
        "book_sections": book_sections
        or [
            {"id": "preface", "title": "Preface"},
            {"id": "appendices", "title": "Appendices"},
        ],
        "families": [{"id": "fam_a", "title": "A", "method_ids": ["m1"]}],
        "methods": [{"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"}],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))


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


def test_main_rejects_from_stage_outside_phase(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")

    try:
        main(["--run-id", "demo", "--phase", "draft", "--resume", "--from-stage", "14"])
    except SystemExit as error:
        assert "stage 14 is not available for phase draft" in str(error)
    else:
        raise AssertionError("expected invalid from-stage failure")


def test_main_write_phase_defaults_to_stage_14(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    calls = []

    for stage in ("14", "15", "16", "17", "18"):
        monkeypatch.setattr(
            f"scripts.run_auto_research.run_stage_{stage}",
            lambda run_dir, stage=stage: calls.append(stage),
        )

    rc = main(["--run-id", "demo", "--phase", "write"])

    assert rc == 0
    assert calls == ["14", "15", "16", "17", "18"]


def test_main_write_phase_rejects_draft_from_stage(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")

    try:
        main(["--run-id", "demo", "--phase", "write", "--from-stage", "11"])
    except SystemExit as error:
        assert "stage 11 is not available for phase write" in str(error)
    else:
        raise AssertionError("expected invalid write from-stage failure")


def test_main_write_phase_rejects_saved_draft_current_stage(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
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


def test_bootstrap_new_run_rejects_unsafe_run_id():
    completed = subprocess.CompletedProcess(
        ["codex"],
        0,
        stdout="RUN_ID=../escape\n",
        stderr="",
    )

    with patch("scripts.run_auto_research.subprocess.run", return_value=completed):
        try:
            bootstrap_new_run("Demo topic", "draft")
        except ValueError as error:
            assert "unsafe run_id" in str(error)
        else:
            raise AssertionError("expected unsafe run_id failure")


def test_bootstrap_new_run_reports_launch_error():
    with patch(
        "scripts.run_auto_research.subprocess.run",
        side_effect=FileNotFoundError("codex"),
    ):
        try:
            bootstrap_new_run("Demo topic", "draft")
        except RuntimeError as error:
            assert "bootstrap failed to launch or complete" in str(error)
        else:
            raise AssertionError("expected bootstrap launch failure")


def test_bootstrap_new_run_reports_missing_run_id_stdout():
    completed = subprocess.CompletedProcess(
        ["codex"],
        0,
        stdout="completed without id\n",
        stderr="",
    )

    with patch("scripts.run_auto_research.subprocess.run", return_value=completed):
        try:
            bootstrap_new_run("Demo topic", "draft")
        except RuntimeError as error:
            assert "bootstrap did not print RUN_ID" in str(error)
            assert "completed without id" in str(error)
        else:
            raise AssertionError("expected missing RUN_ID failure")


def test_main_rejects_topic_write_phase():
    try:
        main(["--topic", "Demo topic", "--phase", "write"])
    except SystemExit as error:
        assert "--topic cannot be used with --phase write" in str(error)
    else:
        raise AssertionError("expected topic write phase failure")
