from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.auto_research_runner.shards import (
    _codex_exec_command,
    expected_outputs_exist,
    run_shards,
)
from scripts.auto_research_runner.shared_types import ShardSpec


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

    def fake_sdk(run_dir, shard, timeout_seconds):
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

    def fake_sdk(run_dir, shard, timeout_seconds):
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
