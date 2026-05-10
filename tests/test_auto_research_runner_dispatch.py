from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from scripts.run_auto_research import ShardSpec, expected_outputs_exist, run_shards


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

    with patch("scripts.run_auto_research.subprocess.run", side_effect=fake_run):
        run_shards(run, [spec], max_retries=1)

    manifest = run / "run_control" / "stages" / "11" / "shards" / "vgraph-01.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["status"] == "completed"
    assert data["attempt"] == 2
    assert calls["count"] == 2


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
        "scripts.run_auto_research.subprocess.run",
        side_effect=FileNotFoundError("codex"),
    ):
        with pytest.raises(RuntimeError):
            run_shards(run, [spec], max_retries=0)

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
        "scripts.run_auto_research.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["codex"], timeout=1),
    ):
        with pytest.raises(RuntimeError):
            run_shards(run, [spec], max_retries=0, timeout_seconds=1)

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

    with patch("scripts.run_auto_research.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError):
            run_shards(run, [spec], max_retries=0, timeout_seconds=1)

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
