from __future__ import annotations

import json
import subprocess
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
