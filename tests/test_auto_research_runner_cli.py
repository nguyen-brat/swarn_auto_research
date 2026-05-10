from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.run_auto_research import (
    build_chapter_targets,
    run_deterministic_command,
    run_stage_18,
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
