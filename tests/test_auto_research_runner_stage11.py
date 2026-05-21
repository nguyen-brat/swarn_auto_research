from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.auto_research_runner.artifacts import (
    build_verified_graph_frame,
    compile_verified_graph_fragment_from_frame,
    merge_verified_graph_fragments,
    run_stage_11_merge,
    sanitize_verified_graph_fragment,
)
from scripts.auto_research_runner.stages import run_stage_11


def _write_fragment(run, arxiv_id, nodes, edges):
    path = run / "11_verified_graph" / "fragments" / f"{arxiv_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for index, edge in enumerate(edges, start=1):
        if isinstance(edge, dict) and "claim_id" not in edge:
            edge["claim_id"] = f"c{index:03d}"
    path.write_text(json.dumps({"arxiv_id": arxiv_id, "nodes": nodes, "edges": edges}))


def _write_weak_fragment(run, arxiv_id, nodes, edges=None):
    path = run / "05_weak_graph" / "fragments" / f"{arxiv_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"arxiv_id": arxiv_id, "nodes": nodes, "edges": edges or []}))


def _write_evidence_sources(run, arxiv_id, sources):
    path = run / "10_verified_evidence" / f"{arxiv_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "claims": [
                    {"source_node_id": source_node_id, "source_lines": source_lines}
                    for source_node_id, source_lines in sources
                ]
            }
        )
    )


def _write_stage11_eligible(run, arxiv_id):
    (run / "07_scoring").mkdir(parents=True, exist_ok=True)
    promoted_path = run / "07_scoring" / "promoted_papers.json"
    promoted = []
    if promoted_path.exists():
        promoted = json.loads(promoted_path.read_text()).get("promoted_papers", [])
    if not any(item.get("arxiv_id") == arxiv_id for item in promoted):
        promoted.append({"arxiv_id": arxiv_id})
    promoted_path.write_text(json.dumps({"promoted_papers": promoted}))
    markdown_path = run / "08_full_markdown" / f"{arxiv_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("# Paper\n")
    tree_path = run / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json"
    nodes_path = run / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    nodes_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "root": {
                    "id": "s.00",
                    "title": "(root)",
                    "children": [
                        {
                            "id": "s.01",
                            "title": "Paper",
                            "level": 1,
                            "start_line": 1,
                            "end_line": 1,
                            "parent_id": "s.00",
                            "summary": "Paper.",
                            "children": [],
                        }
                    ],
                },
            }
        )
    )
    nodes_path.write_text(
        json.dumps(
            {
                "s.01": {
                    "id": "s.01",
                    "title": "Paper",
                    "level": 1,
                    "start_line": 1,
                    "end_line": 1,
                    "parent_id": "s.00",
                    "summary": "Paper.",
                }
            }
        )
    )
    evidence_path = run / "10_verified_evidence" / f"{arxiv_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )


def test_merge_verified_graph_fragments_dedupes_nodes_and_edges(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.1", [1, 2])])
    _write_evidence_sources(run, "1.2", [("s.1", [1, 2]), ("s.2", [3, 4])])
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
        [
            {"id": "1.1", "type": "Paper"},
            {"id": "1.2", "type": "Paper"},
            {"id": "looped-transformer", "type": "Method"},
        ],
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


def test_merge_verified_graph_fragments_rejects_missing_edge_endpoint(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.1", [1])])
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}],
        [{
            "src": "1.1",
            "dst": "missing-method",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.1",
            "source_lines": [1],
        }],
    )

    with pytest.raises(ValueError, match="edge endpoint missing"):
        merge_verified_graph_fragments(run)


def test_merge_verified_graph_fragments_rejects_source_not_in_verified_evidence(tmp_path):
    run = tmp_path / "run"
    evidence_path = run / "10_verified_evidence" / "1.1.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 2]}]})
    )
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "method",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.99",
            "source_lines": [9],
        }],
    )

    with pytest.raises(ValueError, match="edge source not found in verified evidence"):
        merge_verified_graph_fragments(run)


def test_sanitize_verified_graph_fragment_drops_only_invalid_edges(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.01", [1, 2])])
    _write_fragment(
        run,
        "1.1",
        [
            {"id": "1.1", "type": "Paper"},
            {"id": "good", "type": "Method"},
            {"id": "bad", "type": "Method"},
        ],
        [
            {
                "src": "1.1",
                "dst": "good",
                "type": "INTRODUCES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 2],
            },
            {
                "src": "1.1",
                "dst": "bad",
                "type": "INTRODUCES",
                "confidence": "verified",
                "source_node_id": "s.99",
                "source_lines": [9],
            },
        ],
    )

    assert sanitize_verified_graph_fragment(run, "1.1") == 1

    graph = merge_verified_graph_fragments(run)
    assert {node["id"] for node in graph["nodes"]} == {"1.1", "good"}
    assert [(edge["src"], edge["dst"]) for edge in graph["edges"]] == [("1.1", "good")]


def test_sanitize_verified_graph_fragment_writes_repair_event(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.01", [1, 2])])
    _write_fragment(
        run,
        "1.1",
        [
            {"id": "1.1", "type": "Paper"},
            {"id": "good", "type": "Method"},
            {"id": "bad", "type": "Method"},
        ],
        [
            {
                "src": "1.1",
                "dst": "good",
                "type": "INTRODUCES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 2],
            },
            {
                "src": "1.1",
                "dst": "bad",
                "type": "INTRODUCES",
                "confidence": "verified",
                "source_node_id": "s.99",
                "source_lines": [9],
            },
        ],
    )

    sanitize_verified_graph_fragment(run, "1.1")

    event_path = run / "run_control" / "repairs" / "stage_11" / "repair_events.jsonl"
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    assert events[-1]["outcome"] == "attempted"
    assert events[-1]["artifact"] == "11_verified_graph/fragments/1.1.json"
    assert events[-1]["issues"][0]["kind"] == "dropped_invalid_verified_edge"
    raw = json.loads((run / events[-1]["raw_artifact"]).read_text())
    assert len(raw["edges"]) == 2


def test_sanitize_verified_graph_fragment_removes_dangling_invalid_nodes(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.01", [1, 2])])
    _write_fragment(
        run,
        "1.1",
        [
            {"id": "1.1", "type": "Paper"},
            {"id": "bad", "type": "Method"},
        ],
        [{
            "src": "1.1",
            "dst": "bad",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.99",
            "source_lines": [9],
        }],
    )

    assert sanitize_verified_graph_fragment(run, "1.1") == 1

    graph = merge_verified_graph_fragments(run)
    assert graph["nodes"] == [{"id": "1.1", "type": "Paper"}]
    assert graph["edges"] == []


def test_build_verified_graph_frame_writes_claim_ids_and_allowed_nodes(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.01", [1, 1])])
    _write_weak_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
        [],
    )

    frame_path = build_verified_graph_frame(run, "1.1")

    frame = json.loads(frame_path.read_text())
    assert frame["arxiv_id"] == "1.1"
    assert frame["claims"] == [{
        "claim": "",
        "claim_id": "c001",
        "claim_type": "",
        "source_lines": [1, 1],
        "source_node_id": "s.01",
    }]
    assert {node["id"] for node in frame["allowed_nodes"]} == {"1.1", "method"}
    assert "USES" in frame["allowed_edge_types"]


def test_compile_verified_graph_fragment_from_frame_copies_claim_source(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.01", [1, 1])])
    frame_path = build_verified_graph_frame(run, "1.1")
    frame = json.loads(frame_path.read_text())
    frame["allowed_nodes"].append({"id": "method", "type": "Method", "display": "method"})
    frame_path.write_text(json.dumps(frame))
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
        [{
            "claim_id": "c001",
            "src": "1.1",
            "dst": "method",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "wrong",
            "source_lines": [9, 9],
        }],
    )

    assert compile_verified_graph_fragment_from_frame(run, "1.1") == 1

    graph = merge_verified_graph_fragments(run)
    assert graph["edges"] == [{
        "claim_id": "c001",
        "confidence": "verified",
        "dst": "method",
        "source_lines": [1, 1],
        "source_node_id": "s.01",
        "src": "1.1",
        "type": "USES",
    }]


def test_compile_verified_graph_fragment_reports_dropped_claim_id_edges(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_weak_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
    )
    build_verified_graph_frame(run, "1.1")
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}],
        [
            {
                "claim_id": "c001",
                "src": "1.1",
                "dst": "method",
                "type": "USES",
                "confidence": "verified",
            },
            {
                "claim_id": "missing",
                "src": "1.1",
                "dst": "method",
                "type": "USES",
                "confidence": "verified",
            },
        ],
    )

    compile_verified_graph_fragment_from_frame(run, "1.1")

    event_path = run / "run_control" / "repairs" / "stage_11" / "repair_events.jsonl"
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    assert events[-1]["outcome"] == "accepted"
    assert events[-1]["issues"][0]["kind"] == "claim_id_compile_dropped_edge"
    raw = json.loads((run / events[-1]["raw_artifact"]).read_text())
    assert len(raw["edges"]) == 2


def test_compile_verified_graph_fragment_drops_direct_grounded_edges_without_claim_id(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_weak_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
    )
    build_verified_graph_frame(run, "1.1")
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
        [
            {
                "claim_id": None,
                "src": "1.1",
                "dst": "method",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }
        ],
    )

    assert compile_verified_graph_fragment_from_frame(run, "1.1") == 0

    fragment = json.loads((run / "11_verified_graph" / "fragments" / "1.1.json").read_text())
    assert fragment["edges"][0]["claim_id"] is None
    with pytest.raises(ValueError, match="edge missing claim_id"):
        merge_verified_graph_fragments(run, arxiv_ids=["1.1"])


def test_verified_graph_fragment_retry_feedback_handles_malformed_fragment(tmp_path):
    from scripts.auto_research_runner.artifacts import verified_graph_fragment_retry_feedback

    run = tmp_path / "run"
    fragment_path = run / "11_verified_graph" / "fragments" / "1.1.json"
    fragment_path.parent.mkdir(parents=True)
    fragment_path.write_text('{"edges": [')

    feedback = verified_graph_fragment_retry_feedback(run, "1.1")

    assert "Previous Stage 11 fragment failed validation" in feedback
    assert "fragment_json_error" in feedback


def test_merge_verified_graph_fragments_rejects_missing_verified_evidence(tmp_path):
    run = tmp_path / "run"
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "method",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.01",
            "source_lines": [1, 1],
        }],
    )

    with pytest.raises(ValueError, match="missing verified evidence"):
        merge_verified_graph_fragments(run)


def test_merge_verified_graph_fragments_rejects_empty_fragments_dir(tmp_path):
    run = tmp_path / "run"
    (run / "11_verified_graph" / "fragments").mkdir(parents=True)

    with pytest.raises(ValueError, match="no Stage 11 fragment JSON files found"):
        merge_verified_graph_fragments(run)


def test_merge_verified_graph_fragments_rejects_node_missing_id(tmp_path):
    run = tmp_path / "run"
    _write_evidence_sources(run, "1.1", [("s.1", [1])])
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
    _write_evidence_sources(run, "1.1", [("s.1", [1])])
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


def test_run_stage_11_merges_only_verified_eligible_fragments_and_ignores_stale(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_stage11_eligible(run, "1.2")
    (run / "10_verified_evidence" / "1.2.json").write_text(json.dumps({"claims": []}))
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}],
        [{
            "src": "1.1",
            "dst": "1.1",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.01",
            "source_lines": [1, 1],
        }],
    )
    _write_fragment(
        run,
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

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}],
            [{
                "src": "1.1",
                "dst": "1.1",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards) as run_shards:
        run_stage_11(run)

    run_shards.assert_called_once()
    args, kwargs = run_shards.call_args
    assert [spec.expected_outputs for spec in args[1]] == [["11_verified_graph/fragments/1.1.json"]]
    assert kwargs["force"] is True
    graph = json.loads((run / "11_verified_graph" / "global_graph.json").read_text())
    assert {node["id"] for node in graph["nodes"]} == {"1.1"}


def test_run_stage_11_rebuilds_stale_global_graph_when_eligibility_changes(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}],
        [{
            "src": "1.1",
            "dst": "1.1",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.01",
            "source_lines": [1, 1],
        }],
    )
    (run / "11_verified_graph" / "global_graph.json").write_text(
        json.dumps(
            {
                "nodes": [{"id": "1.1", "type": "Paper"}, {"id": "stale", "type": "Paper"}],
                "edges": [
                    {
                        "src": "stale",
                        "dst": "stale",
                        "type": "USES",
                        "confidence": "verified",
                        "source_node_id": "s.9",
                        "source_lines": [9],
                    }
                ],
            }
        )
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}],
            [{
                "src": "1.1",
                "dst": "1.1",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards) as run_shards:
        run_stage_11(run)

    run_shards.assert_called_once()
    args, kwargs = run_shards.call_args
    assert [spec.expected_outputs for spec in args[1]] == [["11_verified_graph/fragments/1.1.json"]]
    assert kwargs["force"] is True
    graph = json.loads((run / "11_verified_graph" / "global_graph.json").read_text())
    assert {node["id"] for node in graph["nodes"]} == {"1.1"}


def test_run_stage_11_rebuilds_fragment_when_verified_evidence_changes(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_weak_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "new-node", "type": "Method"}],
    )
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "old-node", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "old-node",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.old",
            "source_lines": [9],
        }],
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        assert len(specs) == 1
        assert kwargs.get("force") is True
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}, {"id": "new-node", "type": "Method"}],
            [{
                "src": "1.1",
                "dst": "new-node",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    graph = json.loads((run / "11_verified_graph" / "global_graph.json").read_text())
    assert {node["id"] for node in graph["nodes"]} == {"1.1", "new-node"}


def test_run_stage_11_force_removes_stale_fragment_before_dispatch(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "stale-node", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "stale-node",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.01",
            "source_lines": [1, 1],
        }],
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        assert len(specs) == 1
        assert kwargs.get("force") is True
        assert not (run_dir / "11_verified_graph" / "fragments" / "1.1.json").exists()

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        with pytest.raises(RuntimeError, match="Stage 11 still missing fragments"):
            run_stage_11(run)


def test_run_stage_11_clears_stale_quarantine_for_valid_evidence_before_dispatch(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    (run / "10_verified_evidence" / "quarantined_evidence.csv").write_text(
        "arxiv_id,reason\n1.1,no_claims\n"
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        assert len(specs) == 1
        quarantine_path = run_dir / "10_verified_evidence" / "quarantined_evidence.csv"
        assert not quarantine_path.exists() or "1.1,no_claims" not in quarantine_path.read_text()
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}],
            [{
                "src": "1.1",
                "dst": "1.1",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert (run / "11_verified_graph" / "global_graph.json").exists()


def test_run_stage_11_merges_when_all_fragments_already_exist(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "m", "type": "Method"}],
        [{
            "src": "1.1",
            "dst": "m",
            "type": "INTRODUCES",
            "confidence": "verified",
            "source_node_id": "s.01",
            "source_lines": [1, 1],
        }],
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}, {"id": "m", "type": "Method"}],
            [{
                "src": "1.1",
                "dst": "m",
                "type": "INTRODUCES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards) as run_shards:
        run_stage_11(run)

    run_shards.assert_called_once()
    args, kwargs = run_shards.call_args
    assert [spec.expected_outputs for spec in args[1]] == [["11_verified_graph/fragments/1.1.json"]]
    assert kwargs["force"] is True
    assert (run / "11_verified_graph" / "global_graph.json").exists()


def test_run_stage_11_refreshes_all_eligible_fragments(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_stage11_eligible(run, "1.2")
    _write_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}],
        [{
            "src": "1.1",
            "dst": "1.1",
            "type": "USES",
            "confidence": "verified",
            "source_node_id": "s.01",
            "source_lines": [1, 1],
        }],
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        assert len(specs) == 2
        assert kwargs.get("force") is True
        assert [spec.shard_id for spec in specs] == ["vgraph-resume-1.1", "vgraph-resume-1.2"]
        assert [spec.expected_outputs for spec in specs] == [
            ["11_verified_graph/fragments/1.1.json"],
            ["11_verified_graph/fragments/1.2.json"],
        ]
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}],
            [{
                "src": "1.1",
                "dst": "1.1",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )
        _write_fragment(
            run_dir,
            "1.2",
            [{"id": "1.2", "type": "Paper"}],
            [{
                "src": "1.2",
                "dst": "1.2",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert (run / "11_verified_graph" / "global_graph.json").exists()


def test_run_stage_11_retries_fragment_with_unverified_edge_source(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_weak_fragment(
        run,
        "1.1",
        [
            {"id": "1.1", "type": "Paper"},
            {"id": "bad", "type": "Method"},
            {"id": "good", "type": "Method"},
        ],
    )
    calls = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        calls.append([spec.shard_id for spec in specs])
        assert len(specs) == 1
        assert kwargs.get("force") is True
        if len(calls) == 1:
            _write_fragment(
                run_dir,
                "1.1",
                [{"id": "1.1", "type": "Paper"}, {"id": "bad", "type": "Method"}],
                [{
                    "claim_id": None,
                    "src": "1.1",
                    "dst": "bad",
                    "type": "USES",
                    "confidence": "verified",
                    "source_node_id": "s.01",
                    "source_lines": [9, 9],
                }],
            )
            return
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}, {"id": "good", "type": "Method"}],
            [{
                "src": "1.1",
                "dst": "good",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert calls == [["vgraph-resume-1.1"], ["vgraph-resume-1.1"]]
    graph = json.loads((run / "11_verified_graph" / "global_graph.json").read_text())
    assert {node["id"] for node in graph["nodes"]} == {"1.1", "good"}
    assert "11,recovery,1 invalid verified graph fragment(s) retried" in (
        run / "run_log.csv"
    ).read_text()


def test_run_stage_11_retry_prompt_includes_invalid_edges_and_allowed_sources(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_weak_fragment(
        run,
        "1.1",
        [
            {"id": "1.1", "type": "Paper"},
            {"id": "bad", "type": "Method"},
            {"id": "good", "type": "Method"},
        ],
    )
    calls = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        calls.append(specs[0].prompt)
        if len(calls) == 1:
            _write_fragment(
                run_dir,
                "1.1",
                [{"id": "1.1", "type": "Paper"}, {"id": "bad", "type": "Method"}],
                [{
                    "claim_id": None,
                    "src": "1.1",
                    "dst": "bad",
                    "type": "USES",
                    "confidence": "verified",
                    "source_node_id": "s.01",
                    "source_lines": [9, 9],
                }],
            )
            return
        assert "Previous Stage 11 fragment failed validation" in specs[0].prompt
        assert '"source_node_id": "s.01"' in specs[0].prompt
        assert '"source_lines": [9, 9]' in specs[0].prompt
        assert '"source_lines": [1, 1]' in specs[0].prompt
        assert "copy one exact source_node_id + source_lines pair" in specs[0].prompt
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}, {"id": "good", "type": "Method"}],
            [{
                "src": "1.1",
                "dst": "good",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert len(calls) == 2


def test_run_stage_11_compiles_claim_id_fragment_before_validation(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    _write_weak_fragment(
        run,
        "1.1",
        [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
    )
    prompts = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        prompts.append(specs[0].prompt)
        assert "11_verified_graph/frames/1.1.json" in specs[0].prompt
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}, {"id": "method", "type": "Method"}],
            [{
                "claim_id": "c001",
                "src": "1.1",
                "dst": "method",
                "type": "USES",
                "confidence": "verified",
            }],
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert len(prompts) == 1
    graph = json.loads((run / "11_verified_graph" / "global_graph.json").read_text())
    assert graph["edges"][0]["source_node_id"] == "s.01"
    assert graph["edges"][0]["source_lines"] == [1, 1]


def test_run_stage_11_uses_facade_merge_function(tmp_path):
    run = tmp_path / "run"
    _write_stage11_eligible(run, "1.1")
    merged = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        assert len(specs) == 1
        _write_fragment(
            run_dir,
            "1.1",
            [{"id": "1.1", "type": "Paper"}],
            [{
                "src": "1.1",
                "dst": "1.1",
                "type": "USES",
                "confidence": "verified",
                "source_node_id": "s.01",
                "source_lines": [1, 1],
            }],
        )

    def fake_merge(run_dir, arxiv_ids=None):
        merged.append((run_dir, arxiv_ids))

    with (
        patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards),
        patch("scripts.auto_research_runner.stages.run_stage_11_merge", side_effect=fake_merge),
    ):
        run_stage_11(run)

    assert merged == [(run, ["1.1"])]


def test_run_stage_11_uses_flat_fragment_paths_for_old_arxiv_ids(tmp_path):
    run = tmp_path / "run"
    (run / "07_scoring").mkdir(parents=True)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": "hep-th/9901001"}]})
    )
    (run / "08_full_markdown").mkdir(parents=True)
    markdown_path = run / "08_full_markdown" / "hep-th/9901001.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("# Paper\n")
    (run / "09_pageindex" / "trees").mkdir(parents=True)
    (run / "09_pageindex" / "nodes").mkdir(parents=True)
    tree_path = run / "09_pageindex" / "trees" / "hep-th/9901001.tree.json"
    nodes_path = run / "09_pageindex" / "nodes" / "hep-th/9901001.nodes.json"
    tree_path.parent.mkdir(parents=True)
    nodes_path.parent.mkdir(parents=True)
    tree_path.write_text(
        json.dumps(
            {
                "arxiv_id": "hep-th/9901001",
                "root": {
                    "id": "s.00",
                    "title": "(root)",
                    "children": [
                        {
                            "id": "s.01",
                            "title": "Paper",
                            "level": 1,
                            "start_line": 1,
                            "end_line": 1,
                            "parent_id": "s.00",
                            "summary": "Paper.",
                            "children": [],
                        }
                    ],
                },
            }
        )
    )
    nodes_path.write_text(
        json.dumps(
            {
                "s.01": {
                    "id": "s.01",
                    "title": "Paper",
                    "level": 1,
                    "start_line": 1,
                    "end_line": 1,
                    "parent_id": "s.00",
                    "summary": "Paper.",
                }
            }
        )
    )
    evidence_path = run / "10_verified_evidence" / "hep-th/9901001.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
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
                            "claim_id": "c001",
                            "src": "hep-th/9901001",
                        "dst": "hep-th/9901001",
                        "type": "USES",
                        "confidence": "verified",
                        "source_node_id": "s.01",
                        "source_lines": [1, 1],
                    }],
                }
            )
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_11(run)

    assert (run / "11_verified_graph" / "global_graph.json").exists()
