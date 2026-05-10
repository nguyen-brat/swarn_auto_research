from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.run_auto_research import (
    merge_verified_graph_fragments,
    run_stage_11,
    run_stage_11_merge,
)


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
        [
            {
                "src": "1.1",
                "dst": "looped-transformer",
                "type": "INTRODUCES",
                "confidence": "verified",
                "source_node_id": "s.1",
                "source_lines": [1, 2],
            },
            {
                "src": "1.2",
                "dst": "looped-transformer",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.2",
                "source_lines": [3, 4],
            },
        ],
    )

    graph = merge_verified_graph_fragments(run)

    assert {n["id"] for n in graph["nodes"]} == {"1.1", "1.2", "looped-transformer"}
    assert len(graph["edges"]) == 2
    assert all(e["confidence"] == "verified" for e in graph["edges"])
    assert all(e["source_node_id"] for e in graph["edges"])


def test_merge_verified_graph_fragments_rejects_empty_source_lines(tmp_path):
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
            "source_lines": [],
        }],
    )

    with pytest.raises(ValueError):
        merge_verified_graph_fragments(run)


def test_merge_verified_graph_fragments_rejects_empty_fragments_dir(tmp_path):
    run = tmp_path / "run"
    (run / "11_verified_graph" / "fragments").mkdir(parents=True)

    with pytest.raises(ValueError, match="no Stage 11 fragment JSON files found"):
        merge_verified_graph_fragments(run)


def test_merge_verified_graph_fragments_rejects_node_missing_id(tmp_path):
    run = tmp_path / "run"
    _write_fragment(
        run,
        "1.1",
        [{"type": "Paper"}],
        [],
    )

    with pytest.raises(ValueError, match=r"node missing id in .*1\.1\.json"):
        merge_verified_graph_fragments(run)


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
        json.dumps(
            {
                "nodes": [],
                "edges": [
                    {"src": "x", "dst": "y", "type": "USES"},
                    {"src": "a", "dst": "b", "type": "INTRODUCES"},
                    {"src": "c", "dst": "d", "type": "MEASURES"},
                ],
            }
        )
    )

    run_stage_11_merge(run)

    global_graph = run / "11_verified_graph" / "global_graph.json"
    report = run / "11_verified_graph" / "graph_report.md"
    assert global_graph.exists()
    assert report.exists()
    report_text = report.read_text()
    assert "Verified graph report" in report_text
    assert "- Nodes: 2" in report_text
    assert "- Verified edges: 1" in report_text
    assert "- Weak edges not promoted: 2" in report_text
    assert "11,merged" in (run / "run_log.csv").read_text()


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
        assert specs[0].shard_id == "vgraph-resume-1.2"
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


def test_run_stage_11_uses_flat_fragment_paths_for_old_arxiv_ids(tmp_path):
    run = tmp_path / "run"
    (run / "07_scoring").mkdir(parents=True)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": "hep-th/9901001"}]})
    )

    def fake_run_shards(run_dir, specs, max_retries=1):
        assert len(specs) == 1
        assert specs[0].shard_id == "vgraph-resume-hep-thpct2F9901001"
        assert specs[0].expected_outputs == [
            "11_verified_graph/fragments/hep-th%2F9901001.json"
        ]
        path = run_dir / specs[0].expected_outputs[0]
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "arxiv_id": "hep-th/9901001",
                    "nodes": [{"id": "hep-th/9901001", "type": "Paper"}],
                    "edges": [{
                        "src": "hep-th/9901001",
                        "dst": "hep-th/9901001",
                        "type": "USES",
                        "confidence": "verified",
                        "source_node_id": "s.1",
                        "source_lines": [1],
                    }],
                }
            )
        )

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert (run / "11_verified_graph" / "global_graph.json").exists()
