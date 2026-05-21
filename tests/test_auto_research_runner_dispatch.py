from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sdk.codex_app_server.errors import TransportClosedError
from scripts.auto_research_runner.shards import (
    _cli_output_timeout_seconds,
    _codex_exec_command,
    expected_outputs_exist,
    run_shards,
)
from scripts.auto_research_runner.shared_types import ShardAttemptResult, ShardSpec


def test_expected_outputs_exist_requires_every_file(tmp_path):
    run = tmp_path / "run"
    spec = ShardSpec(
        stage="11",
        shard_id="vgraph-01",
        agent="verified_graph_extractor",
        model="gpt-5.4-mini",
        prompt="p",
        expected_outputs=[
            "11_verified_graph/fragments/1.json",
            "11_verified_graph/fragments/2.json",
        ],
    )
    (run / "11_verified_graph" / "fragments").mkdir(parents=True)
    (run / "11_verified_graph" / "fragments" / "1.json").write_text("{}")

    assert expected_outputs_exist(run, spec) is False

    (run / "11_verified_graph" / "fragments" / "2.json").write_text("{}")
    assert expected_outputs_exist(run, spec) is True


def test_codex_exec_command_uses_current_noninteractive_flags():
    spec = ShardSpec(
        stage="12",
        shard_id="outline",
        agent="outline_planner",
        model="gpt-5.4-mini",
        prompt="write outline",
        expected_outputs=["12_taxonomy/outline.json"],
    )

    command = _codex_exec_command(spec)

    assert "--ask-for-approval" not in command
    assert command[0:2] == ["codex", "exec"]
    assert command[command.index("-c") + 1] == 'approval_policy="never"'
    assert command[command.index("--sandbox") + 1] == "workspace-write"


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

    def fake_run(cmd, cwd, text, stdout, stderr, timeout):
        calls["count"] += 1
        if calls["count"] == 2:
            out = run / "11_verified_graph" / "fragments" / "1.json"
            out.parent.mkdir(parents=True)
            out.write_text(json.dumps({"nodes": [], "edges": []}))
        return subprocess.CompletedProcess(cmd, 0)

    with patch("scripts.auto_research_runner.shards.subprocess.run", side_effect=fake_run):
        run_shards(run, [spec], max_retries=1, executor="cli")

    manifest = run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["status"] == "completed"
    assert data["attempt"] == 2
    assert calls["count"] == 2


def test_run_shards_recovers_parallel_capacity_failure_serially(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    good = ShardSpec(
        stage="14",
        shard_id="write-good",
        agent="method_chapter_writer",
        model="gpt-5.4",
        prompt="write the good chapter",
        expected_outputs=["14_chapters/methods/good.md"],
    )
    flaky = ShardSpec(
        stage="14",
        shard_id="write-flaky",
        agent="method_chapter_writer",
        model="gpt-5.4",
        prompt="write the flaky chapter",
        expected_outputs=["14_chapters/methods/flaky.md"],
    )
    calls = {"write-good": 0, "write-flaky": 0}

    def fake_sdk(run_dir, shard, timeout_seconds, **_kwargs):
        calls[shard.shard_id] += 1
        if shard.shard_id == "write-flaky" and calls[shard.shard_id] < 3:
            raise RuntimeError("Selected model is at capacity. Please try a different model.")
        out = run_dir / shard.expected_outputs[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# {shard.shard_id}\n")
        return SimpleNamespace(
            returncode=0,
            stdout="ok",
            stderr="",
            executor="sdk",
            thread_id=f"thread-{shard.shard_id}-{calls[shard.shard_id]}",
            turn_id=f"turn-{shard.shard_id}-{calls[shard.shard_id]}",
        )

    with patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fake_sdk):
        run_shards(run, [good, flaky], max_retries=1, max_workers=2)

    assert (run / "14_chapters" / "methods" / "good.md").exists()
    assert (run / "14_chapters" / "methods" / "flaky.md").exists()
    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "write-flaky.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert manifest["attempt"] == 3
    assert calls == {"write-good": 1, "write-flaky": 3}


def test_run_shards_force_recovery_retries_only_missing_outputs(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    good = ShardSpec(
        stage="10",
        shard_id="verified-evidence-good",
        agent="verified_evidence_extractor",
        model="gpt-5.4-mini",
        prompt="write good evidence",
        expected_outputs=["10_verified_evidence/good.json"],
    )
    flaky = ShardSpec(
        stage="10",
        shard_id="verified-evidence-flaky",
        agent="verified_evidence_extractor",
        model="gpt-5.4-mini",
        prompt="write flaky evidence",
        expected_outputs=["10_verified_evidence/flaky.json"],
    )
    calls = {"verified-evidence-good": 0, "verified-evidence-flaky": 0}

    def fake_single_shard(run_dir, shard, **_kwargs):
        calls[shard.shard_id] += 1
        if shard.shard_id == "verified-evidence-good":
            out = run_dir / shard.expected_outputs[0]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]}))
            return
        if calls[shard.shard_id] == 1:
            raise RuntimeError("temporary parallel failure")
        out = run_dir / shard.expected_outputs[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]}))

    with patch("scripts.auto_research_runner.shards._run_single_shard", side_effect=fake_single_shard):
        run_shards(run, [good, flaky], max_workers=2, force=True)

    assert (run / "10_verified_evidence" / "good.json").exists()
    assert (run / "10_verified_evidence" / "flaky.json").exists()
    assert calls == {"verified-evidence-good": 1, "verified-evidence-flaky": 2}


def test_run_shards_force_sdk_timeout_does_not_accept_stale_output(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    output.parent.mkdir(parents=True)
    output.write_text("# stale\n")
    spec = ShardSpec(
        stage="14",
        shard_id="rewrite-book-001",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite goals",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )
    calls = []

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("sdk")
        raise TimeoutError("Timed out waiting for app-server message after 1.0s")

    def pass_cli(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("cli")
        output.write_text("# fresh\n")
        return ShardAttemptResult(returncode=0, stdout="ok", stderr="", executor="cli")

    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch(
            "scripts.auto_research_runner.shards._run_cli_shard_attempt_until_outputs",
            side_effect=pass_cli,
        ),
    ):
        run_shards(run, [spec], max_retries=0, executor="sdk-cli-fallback", force=True)

    assert calls == ["sdk", "cli"]
    assert output.read_text() == "# fresh\n"


def test_run_shards_sdk_cli_fallback_stops_cli_after_fresh_output(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    output.parent.mkdir(parents=True)
    output.write_text("# stale\n")
    spec = ShardSpec(
        stage="14",
        shard_id="rewrite-book-001",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite goals",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        raise TimeoutError("Timed out waiting for app-server message after 1.0s")

    monkeypatch.setenv("SWARN_CLI_OUTPUT_SETTLE_SECONDS", "0.1")
    command = [
        sys.executable,
        "-c",
        (
            "import pathlib, time; "
            f"pathlib.Path({str(output)!r}).write_text('# fresh\\n'); "
            "time.sleep(30)"
        ),
    ]
    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch("scripts.auto_research_runner.shards._codex_exec_command", return_value=command),
    ):
        run_shards(
            run,
            [spec],
            max_retries=0,
            executor="sdk-cli-fallback",
            force=True,
            timeout_seconds=5,
        )

    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "rewrite-book-001.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert output.read_text() == "# fresh\n"
    stderr = (
        run / "run_control" / "stages" / "14" / "shards" / "rewrite-book-001.attempt-1.stderr.txt"
    ).read_text()
    assert "CLI executor produced expected outputs but did not exit" in stderr


def test_run_shards_sdk_cli_fallback_bounds_cli_without_outputs(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    spec = ShardSpec(
        stage="15",
        shard_id="verify-003",
        agent="verifier",
        model="gpt-5.4",
        prompt="verify chapters",
        expected_outputs=[
            "15_verification/book/method_taxonomy_verification.json",
            "15_verification/book/shared_examples_verification.json",
        ],
    )

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        raise TimeoutError("Timed out waiting for app-server message after 1.0s")

    monkeypatch.setenv("SWARN_STAGE_15_CLI_OUTPUT_TIMEOUT_SECONDS", "0.2")
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch("scripts.auto_research_runner.shards._codex_exec_command", return_value=command),
    ):
        with pytest.raises(RuntimeError, match="did not produce expected outputs"):
            run_shards(
                run,
                [spec],
                max_retries=0,
                executor="sdk-cli-fallback",
                timeout_seconds=5,
            )

    manifest = json.loads(
        (run / "run_control" / "stages" / "15" / "shards" / "verify-003.json").read_text()
    )
    assert manifest["status"] == "failed"
    stderr = (
        run / "run_control" / "stages" / "15" / "shards" / "verify-003.attempt-1.stderr.txt"
    ).read_text()
    assert "TimeoutExpired" in stderr


def test_run_shards_sdk_cli_fallback_does_not_deadlock_on_noisy_cli(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "15_verification" / "book" / "evaluation_outlook_verification.json"
    spec = ShardSpec(
        stage="15",
        shard_id="verify-004",
        agent="verifier",
        model="gpt-5.4",
        prompt="verify chapter",
        expected_outputs=["15_verification/book/evaluation_outlook_verification.json"],
    )

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        raise TimeoutError("Timed out waiting for app-server message after 1.0s")

    monkeypatch.setenv("SWARN_STAGE_15_CLI_OUTPUT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("SWARN_CLI_OUTPUT_SETTLE_SECONDS", "0.1")
    command = [
        sys.executable,
        "-c",
        (
            "import pathlib, sys, time; "
            "sys.stderr.write('x' * 2_000_000); sys.stderr.flush(); "
            f"pathlib.Path({str(output)!r}).parent.mkdir(parents=True, exist_ok=True); "
            f"pathlib.Path({str(output)!r}).write_text('{{}}'); "
            "time.sleep(30)"
        ),
    ]
    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch("scripts.auto_research_runner.shards._codex_exec_command", return_value=command),
    ):
        run_shards(
            run,
            [spec],
            max_retries=0,
            executor="sdk-cli-fallback",
            timeout_seconds=10,
        )

    assert output.exists()
    manifest = json.loads(
        (run / "run_control" / "stages" / "15" / "shards" / "verify-004.json").read_text()
    )
    assert manifest["status"] == "completed"


def test_run_shards_sdk_cli_fallback_uses_cli_when_sdk_transport_closes(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    spec = ShardSpec(
        stage="14",
        shard_id="write-book-002",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="write goals",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )
    calls = []

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("sdk")
        raise TransportClosedError("app-server closed stdout")

    def pass_cli(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("cli")
        output.parent.mkdir(parents=True)
        output.write_text("# fresh\n")
        return ShardAttemptResult(returncode=0, stdout="ok", stderr="", executor="cli")

    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch(
            "scripts.auto_research_runner.shards._run_cli_shard_attempt_until_outputs",
            side_effect=pass_cli,
        ),
    ):
        run_shards(run, [spec], max_retries=0, executor="sdk-cli-fallback")

    assert calls == ["sdk", "cli"]
    assert output.read_text() == "# fresh\n"


def test_run_shards_sdk_cli_fallback_uses_cli_when_sdk_stream_disconnects(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "00_input" / "search_plan.json"
    spec = ShardSpec(
        stage="1",
        shard_id="seed-pool",
        agent="query_planner",
        model="gpt-5.4",
        prompt="write search plan",
        expected_outputs=["00_input/search_plan.json"],
    )
    calls = []

    def fail_sdk(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("sdk")
        error = RuntimeError(
            "stream disconnected before completion: error sending request for url "
            "(https://chatgpt.com/backend-api/codex/responses)"
        )
        error.sdk_meta = {"thread_id": "thread-disconnected", "turn_id": "turn-disconnected"}
        raise error

    def pass_cli(_run_dir, _spec, _timeout_seconds, **_kwargs):
        calls.append("cli")
        output.parent.mkdir(parents=True)
        output.write_text('{"aspects": []}\n')
        return ShardAttemptResult(returncode=0, stdout="ok", stderr="", executor="cli")

    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch(
            "scripts.auto_research_runner.shards._run_cli_shard_attempt_until_outputs",
            side_effect=pass_cli,
        ),
    ):
        run_shards(run, [spec], max_retries=0, executor="sdk-cli-fallback")

    assert calls == ["sdk", "cli"]
    manifest = json.loads(
        (run / "run_control" / "stages" / "1" / "shards" / "seed-pool.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert manifest["executor"] == "cli"
    stderr = (
        run / "run_control" / "stages" / "1" / "shards" / "seed-pool.attempt-1.stderr.txt"
    ).read_text()
    assert "retried with CLI executor" in stderr


def test_run_shards_force_sdk_timeout_accepts_fresh_output(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    output.parent.mkdir(parents=True)
    output.write_text("# stale\n")
    spec = ShardSpec(
        stage="14",
        shard_id="rewrite-book-001",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite goals",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )
    calls = []

    def fail_sdk(run_dir, shard, _timeout_seconds, **_kwargs):
        calls.append("sdk")
        (run_dir / shard.expected_outputs[0]).write_text("# fresh\n")
        raise TimeoutError("Timed out waiting for app-server message after 1.0s")

    def fail_cli(_spec, _timeout_seconds):
        calls.append("cli")
        raise AssertionError("CLI fallback should not run after fresh forced output")

    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk),
        patch("scripts.auto_research_runner.shards._run_cli_shard_attempt", side_effect=fail_cli),
    ):
        run_shards(run, [spec], max_retries=0, executor="sdk-cli-fallback", force=True)

    assert calls == ["sdk"]
    assert output.read_text() == "# fresh\n"


def test_run_shards_force_returncode_zero_retries_stale_output(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    output.parent.mkdir(parents=True)
    output.write_text("# stale\n")
    spec = ShardSpec(
        stage="14",
        shard_id="rewrite-book-001",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite goals",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )
    calls = 0

    def fake_sdk(run_dir, shard, _timeout_seconds, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            (run_dir / shard.expected_outputs[0]).write_text("# fresh\n")
        return ShardAttemptResult(returncode=0, stdout="ok", stderr="", executor="sdk")

    with patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fake_sdk):
        run_shards(run, [spec], max_retries=1, executor="sdk", force=True)

    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "rewrite-book-001.json").read_text()
    )
    assert calls == 2
    assert manifest["attempt"] == 2
    assert manifest["status"] == "completed"
    assert output.read_text() == "# fresh\n"


def test_run_shards_force_accepts_partial_multi_output_refresh(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    first = run / "14_chapters" / "book" / "03_goals.md"
    second = run / "14_chapters" / "book" / "04_method_taxonomy.md"
    first.parent.mkdir(parents=True)
    first.write_text("# stale goals\n")
    second.write_text("# stale taxonomy\n")
    spec = ShardSpec(
        stage="14",
        shard_id="rewrite-book-001",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite goals and taxonomy",
        expected_outputs=[
            "14_chapters/book/03_goals.md",
            "14_chapters/book/04_method_taxonomy.md",
        ],
    )
    calls = 0

    def fake_sdk(run_dir, shard, _timeout_seconds, **_kwargs):
        nonlocal calls
        calls += 1
        (run_dir / shard.expected_outputs[0]).write_text(f"# fresh goals {calls}\n")
        return ShardAttemptResult(returncode=0, stdout="ok", stderr="", executor="sdk")

    with patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fake_sdk):
        run_shards(run, [spec], max_retries=0, executor="sdk", force=True)

    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "rewrite-book-001.json").read_text()
    )
    assert calls == 1
    assert manifest["attempt"] == 1
    assert manifest["status"] == "completed"
    assert first.read_text() == "# fresh goals 1\n"
    assert second.read_text() == "# stale taxonomy\n"


def test_cli_output_timeout_defaults_to_full_shard_timeout(monkeypatch):
    monkeypatch.delenv("SWARN_CLI_OUTPUT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SWARN_STAGE_11_CLI_OUTPUT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("SWARN_STAGE_11_SDK_NOTIFICATION_TIMEOUT_SECONDS", "300")

    assert _cli_output_timeout_seconds(900, stage="11") == 900.0


def test_run_shards_parallel_force_recovery_retries_failed_stale_output(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    output.parent.mkdir(parents=True)
    output.write_text("# stale\n")
    good = ShardSpec(
        stage="14",
        shard_id="rewrite-good",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite good",
        expected_outputs=["14_chapters/book/00_preface.md"],
    )
    stale = ShardSpec(
        stage="14",
        shard_id="rewrite-stale",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="rewrite stale",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )
    calls = {"rewrite-good": 0, "rewrite-stale": 0}

    def fake_single_shard(run_dir, shard, **kwargs):
        calls[shard.shard_id] += 1
        if shard.shard_id == "rewrite-good":
            out = run_dir / shard.expected_outputs[0]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("# good\n")
            return
        if calls[shard.shard_id] == 1:
            raise RuntimeError("parallel failed before rewriting")
        output.write_text("# fresh\n")

    with patch("scripts.auto_research_runner.shards._run_single_shard", side_effect=fake_single_shard):
        run_shards(run, [good, stale], max_workers=2, force=True)

    assert calls == {"rewrite-good": 1, "rewrite-stale": 2}
    assert output.read_text() == "# fresh\n"


def test_run_shards_defaults_to_sdk_and_records_thread_ids(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    spec = ShardSpec(
        stage="14",
        shard_id="write-001",
        agent="method_chapter_writer",
        model="gpt-5.4",
        prompt="write the chapter",
        expected_outputs=["14_chapters/methods/m1.md"],
    )

    def fake_sdk(run_dir, shard, timeout_seconds, **_kwargs):
        out = run_dir / shard.expected_outputs[0]
        out.parent.mkdir(parents=True)
        out.write_text("# M1\n")
        return SimpleNamespace(
            returncode=0,
            stdout="ok",
            stderr="",
            executor="sdk",
            thread_id="thread-123",
            turn_id="turn-456",
        )

    with (
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fake_sdk),
        patch("scripts.auto_research_runner.shards.subprocess.run") as subprocess_run,
    ):
        run_shards(run, [spec])

    subprocess_run.assert_not_called()
    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "write-001.json").read_text()
    )
    assert manifest["executor"] == "sdk"
    assert manifest["thread_id"] == "thread-123"
    assert manifest["turn_id"] == "turn-456"
    index = run / "run_control" / "stages" / "14" / "sdk_threads.jsonl"
    assert "thread-123" in index.read_text()


def test_stage_14_sdk_attempt_passes_stable_artifact_signature(tmp_path, monkeypatch):
    import scripts.auto_research_runner.shards as shards_mod

    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "methods" / "m1.md"
    spec = ShardSpec(
        stage="14",
        shard_id="write-methods-001",
        agent="method_chapter_writer",
        model="gpt-5.4",
        prompt="write the chapter",
        expected_outputs=["14_chapters/methods/m1.md"],
    )
    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        assert kwargs["artifact_signature"]() is None
        output.parent.mkdir(parents=True)
        output.write_text("# M1\n")
        first = kwargs["artifact_signature"]()
        second = kwargs["artifact_signature"]()
        assert first == second
        assert isinstance(first, tuple)
        return SimpleNamespace(
            thread_id="thread-artifact",
            turn_id="turn-artifact",
            final_response="accepted after expected outputs became stable",
        )

    import sdk.codex as codex_module

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)
    monkeypatch.setenv("SWARN_STAGE_14_SDK_ARTIFACT_SETTLE_SECONDS", "0.01")

    shards_mod.run_shards(run, [spec], executor="sdk", max_retries=0)

    assert observed["artifact_signature"] is not None
    assert observed["artifact_settle_seconds"] == 0.01
    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "write-methods-001.json").read_text()
    )
    assert manifest["thread_id"] == "thread-artifact"
    assert manifest["turn_id"] == "turn-artifact"


def test_stage_1_sdk_attempt_passes_stable_artifact_signature(tmp_path, monkeypatch):
    import scripts.auto_research_runner.shards as shards_mod

    run = tmp_path / "run"
    run.mkdir()
    output = run / "00_input" / "search_plan.json"
    spec = ShardSpec(
        stage="1",
        shard_id="seed-pool",
        agent="query_planner",
        model="gpt-5.4",
        prompt="write search plan",
        expected_outputs=["00_input/search_plan.json"],
    )
    observed = {}

    def fake_run_one_shot_sync(**kwargs):
        observed.update(kwargs)
        assert kwargs["artifact_signature"]() is None
        output.parent.mkdir(parents=True)
        output.write_text('{"aspects": []}\n')
        assert kwargs["artifact_signature"]() is not None
        return SimpleNamespace(
            thread_id="thread-stage-1",
            turn_id="turn-stage-1",
            final_response="accepted after expected outputs became stable",
        )

    import sdk.codex as codex_module

    monkeypatch.setattr(codex_module, "run_one_shot_sync", fake_run_one_shot_sync)

    shards_mod.run_shards(run, [spec], executor="sdk", max_retries=0)

    assert observed["artifact_signature"] is not None
    manifest = json.loads(
        (run / "run_control" / "stages" / "1" / "shards" / "seed-pool.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert manifest["thread_id"] == "thread-stage-1"
    assert manifest["turn_id"] == "turn-stage-1"


def test_sdk_timeout_acceptance_records_sdk_ids(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    output = run / "14_chapters" / "book" / "03_goals.md"
    spec = ShardSpec(
        stage="14",
        shard_id="write-book-003",
        agent="book_section_writer",
        model="gpt-5.4",
        prompt="write goals",
        expected_outputs=["14_chapters/book/03_goals.md"],
    )

    def fail_sdk(run_dir, shard, _timeout_seconds, **_kwargs):
        output.parent.mkdir(parents=True)
        output.write_text("# goals\n")
        error = TimeoutError("Timed out waiting for app-server message after 1.0s")
        error.sdk_meta = {"thread_id": "thread-timeout", "turn_id": "turn-timeout"}
        raise error

    with patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt", side_effect=fail_sdk):
        run_shards(run, [spec], executor="sdk-cli-fallback", max_retries=0)

    manifest = json.loads(
        (run / "run_control" / "stages" / "14" / "shards" / "write-book-003.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert manifest["executor"] == "sdk"
    assert manifest["thread_id"] == "thread-timeout"
    assert manifest["turn_id"] == "turn-timeout"
    index = run / "run_control" / "stages" / "14" / "sdk_threads.jsonl"
    assert "thread-timeout" in index.read_text()


def test_run_shards_cli_executor_uses_subprocess(tmp_path):
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

    def fake_run(cmd, cwd, text, stdout, stderr, timeout):
        out = run / "11_verified_graph" / "fragments" / "1.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"nodes": [], "edges": []}))
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("scripts.auto_research_runner.shards.subprocess.run", side_effect=fake_run) as subprocess_run,
        patch("scripts.auto_research_runner.shards._run_sdk_shard_attempt") as sdk_run,
    ):
        run_shards(run, [spec], executor="cli")

    assert subprocess_run.called
    sdk_run.assert_not_called()
    manifest = json.loads(
        (run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json").read_text()
    )
    assert manifest["executor"] == "cli"


def test_run_shards_records_manifest_and_log_on_launch_error(tmp_path):
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

    with patch(
        "scripts.auto_research_runner.shards.subprocess.run",
        side_effect=FileNotFoundError("codex"),
    ):
        with pytest.raises(RuntimeError):
            run_shards(run, [spec], max_retries=0, executor="cli")

    manifest = run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json"
    data = json.loads(manifest.read_text())
    assert data["status"] == "failed"
    assert data["returncode"] is None
    assert "FileNotFoundError" in (
        run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.attempt-1.stderr.txt"
    ).read_text()
    assert "11,failed,vgraph-01 missing expected outputs" in (
        run / "run_log.csv"
    ).read_text()


def test_run_shards_records_manifest_on_timeout(tmp_path):
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

    with patch(
        "scripts.auto_research_runner.shards.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["codex"], timeout=1),
    ):
        with pytest.raises(RuntimeError):
            run_shards(run, [spec], max_retries=0, timeout_seconds=1, executor="cli")

    manifest = run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json"
    data = json.loads(manifest.read_text())
    assert data["status"] == "failed"
    assert data["returncode"] is None
    assert "TimeoutExpired" in (
        run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.attempt-1.stderr.txt"
    ).read_text()


def test_run_shards_treats_timeout_as_failure_even_if_output_exists(tmp_path):
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

    def fake_run(cmd, cwd, text, stdout, stderr, timeout):
        out = run / "11_verified_graph" / "fragments" / "1.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"nodes": [], "edges": []}))
        raise subprocess.TimeoutExpired(cmd, timeout=timeout)

    with patch("scripts.auto_research_runner.shards.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError):
            run_shards(run, [spec], max_retries=0, timeout_seconds=1, executor="cli")

    manifest = run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json"
    data = json.loads(manifest.read_text())
    assert data["status"] == "failed"
    assert "11,failed,vgraph-01 missing expected outputs" in (
        run / "run_log.csv"
    ).read_text()


def test_run_shards_rejects_unsafe_paths(tmp_path):
    run = tmp_path / "run"
    run.mkdir()

    with pytest.raises(ValueError, match="unsafe shard_id"):
        run_shards(
            run,
            [
                ShardSpec(
                    stage="11",
                    shard_id="../vgraph",
                    agent="verified_graph_extractor",
                    model="gpt-5.4-mini",
                    prompt="write the fragment",
                    expected_outputs=["11_verified_graph/fragments/1.json"],
                )
            ],
        )

    with pytest.raises(ValueError, match="unsafe expected output"):
        expected_outputs_exist(
            run,
            ShardSpec(
                stage="11",
                shard_id="vgraph-01",
                agent="verified_graph_extractor",
                model="gpt-5.4-mini",
                prompt="write the fragment",
                expected_outputs=["../escape.json"],
            ),
        )

    with pytest.raises(ValueError, match="unsafe stage"):
        run_shards(
            run,
            [
                ShardSpec(
                    stage="../11",
                    shard_id="vgraph-01",
                    agent="verified_graph_extractor",
                    model="gpt-5.4-mini",
                    prompt="write the fragment",
                    expected_outputs=["11_verified_graph/fragments/1.json"],
                )
            ],
        )
