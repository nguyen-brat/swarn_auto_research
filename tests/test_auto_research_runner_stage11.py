from __future__ import annotations

import json

from scripts.run_auto_research import merge_verified_graph_fragments, run_stage_11_merge


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
        [{
            "src": "1.2",
            "dst": "looped-transformer",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.2",
            "source_lines": [3, 4],
        }],
    )

    graph = merge_verified_graph_fragments(run)

    assert {n["id"] for n in graph["nodes"]} == {"1.1", "1.2", "looped-transformer"}
    assert len(graph["edges"]) == 2
    assert all(e["confidence"] == "verified" for e in graph["edges"])
    assert all(e["source_node_id"] for e in graph["edges"])


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
        json.dumps({"nodes": [], "edges": [{"src": "x", "dst": "y", "type": "USES"}]})
    )

    run_stage_11_merge(run)

    global_graph = run / "11_verified_graph" / "global_graph.json"
    report = run / "11_verified_graph" / "graph_report.md"
    assert global_graph.exists()
    assert report.exists()
    assert "Verified graph report" in report.read_text()
    assert "11,merged" in (run / "run_log.csv").read_text()
