from __future__ import annotations

import csv
import json
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.run_auto_research as runner
from scripts.run_auto_research import (
    ShardSpec,
    bootstrap_new_run,
    build_deterministic_stage_13_packs,
    build_chapter_targets,
    main,
    run_deterministic_command,
    run_shards,
    run_stage_1,
    run_stage_2,
    run_stage_3,
    run_stage_4,
    run_stage_5,
    run_stage_6,
    run_stage_7,
    run_stage_8,
    run_stage_9,
    run_stage_10,
    run_stage_13,
    run_stage_14,
    run_stage_15,
    run_stage_16,
    run_stage_18,
    save_run_state,
    validate_bootstrap_stage_0_10_contract,
    validate_stage_1_keep_all_contract,
)


def test_default_shard_timeout_allows_long_verifier_turns():
    assert runner.DEFAULT_SHARD_TIMEOUT_SECONDS == 3 * 3600


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


def test_run_shards_honors_max_workers_20(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    active = 0
    max_seen = 0
    lock = threading.Lock()

    def fake_run(cmd, cwd, text, stdout, stderr, timeout):
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        try:
            output_path = run / cmd[-1]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok\n")
            time.sleep(0.03)
            return subprocess.CompletedProcess(cmd, 0)
        finally:
            with lock:
                active -= 1

    specs = [
        ShardSpec(
            stage="14",
            shard_id=f"parallel-{idx:03d}",
            agent="method_chapter_writer",
            model="gpt-5.4",
            prompt=f"out/{idx}.txt",
            expected_outputs=[f"out/{idx}.txt"],
        )
        for idx in range(20)
    ]

    with patch("scripts.run_auto_research.subprocess.run", side_effect=fake_run):
        run_shards(run, specs, max_workers=20, executor="cli")

    assert max_seen > 1
    assert all((run / f"out/{idx}.txt").exists() for idx in range(20))


def test_run_single_shard_records_traceback_on_exception(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec = runner.ShardSpec(
        stage="99",
        shard_id="boom",
        agent="broken_agent",
        model="gpt-5.4-mini",
        prompt="fail",
        expected_outputs=["out.txt"],
    )

    def fail_attempt(*args, **kwargs):
        raise ValueError("specific boom")

    monkeypatch.setattr(runner, "_run_shard_attempt", fail_attempt)

    with pytest.raises(RuntimeError):
        runner._run_single_shard(run_dir, spec, max_retries=0)

    stderr = (
        run_dir
        / "run_control"
        / "stages"
        / "99"
        / "shards"
        / "boom.attempt-1.stderr.txt"
    ).read_text()
    assert "sdk_thread=n/a sdk_turn=n/a" in stderr
    assert "Traceback (most recent call last)" in stderr
    assert "ValueError: specific boom" in stderr


def test_append_run_log_writes_single_header_under_repeated_calls(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    for idx in range(20):
        runner.append_run_log(run_dir, "x", "status", f"detail {idx}")

    rows = list(csv.reader((run_dir / "run_log.csv").open()))
    assert rows[0] == ["timestamp", "stage", "status", "detail"]
    assert rows.count(["timestamp", "stage", "status", "detail"]) == 1
    assert len(rows) == 21


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


def test_run_stage_1_dispatches_query_planner_and_requires_pool_report(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend(specs)
        (run / "00_input").mkdir(parents=True, exist_ok=True)
        (run / "01_seed_pool").mkdir(parents=True, exist_ok=True)
        (run / "02_paper_pool").mkdir(parents=True, exist_ok=True)
        aspects = [
            {
                "aspect_id": f"aspect_{idx}",
                "normal_queries": [f"normal {idx}"],
                "survey_queries": [f"survey {idx}"],
                "positive_keywords": [f"keyword {idx}"],
            }
            for idx in range(4)
        ]
        (run / "00_input" / "search_plan.json").write_text(
            json.dumps({"topic": "Demo", "aspects": aspects})
        )
        bulk_path = run / "01_seed_pool" / "bulk_search_results_123.json"
        ids = [f"2501.{idx:05d}" for idx in range(40)]
        bulk_path.write_text(json.dumps({"papers": ids}))
        (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
            json.dumps(
                {
                    "papers": {arxiv_id: "abstract" for arxiv_id in ids},
                    "total_kept": 40,
                    "output_path": str(bulk_path),
                }
            )
        )
        (run / "02_paper_pool" / "paper_pool.json").write_text(
            json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
        )
        (run / "02_paper_pool" / "paper_pool.csv").write_text(
            "arxiv_id\n" + "\n".join(ids) + "\n"
        )
        (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
            json.dumps(
                {
                    "raw_kept": 40,
                    "selected_total": 40,
                    "selection_policy": "keep_all_bulk_search_results",
                    "per_aspect_selected": {},
                }
            )
        )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_1(run)

    assert len(calls) == 1
    assert calls[0].stage == "1"
    assert calls[0].agent == "query_planner"
    assert "Run Stage 1 only" in calls[0].prompt
    assert "candidate_pool_report.json" in calls[0].prompt
    assert "from every paper in seed_pool_raw" in calls[0].prompt
    assert "Build a stratified" not in calls[0].prompt


def _write_stage_1_contract_artifacts(run, *, raw_count=45, selected_count=None):
    if selected_count is None:
        selected_count = raw_count
    (run / "00_input").mkdir(parents=True, exist_ok=True)
    (run / "01_seed_pool").mkdir(parents=True, exist_ok=True)
    (run / "02_paper_pool").mkdir(parents=True, exist_ok=True)
    aspects = [
        {
            "aspect_id": f"aspect_{idx}",
            "normal_queries": [f"normal {idx}"],
            "survey_queries": [f"survey {idx}"],
            "positive_keywords": [f"keyword {idx}"],
        }
        for idx in range(4)
    ]
    (run / "00_input" / "search_plan.json").write_text(
        json.dumps({"topic": "Demo", "aspects": aspects})
    )
    raw_ids = [f"2501.{idx:05d}" for idx in range(raw_count)]
    selected_ids = raw_ids[:selected_count]
    bulk_path = run / "01_seed_pool" / "bulk_search_results_123.json"
    bulk_path.write_text(json.dumps({"papers": raw_ids}))
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": {arxiv_id: "abstract" for arxiv_id in raw_ids},
                "total_kept": len(raw_ids),
                "output_path": str(bulk_path),
            }
        )
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in selected_ids])
    )
    (run / "02_paper_pool" / "paper_pool.csv").write_text(
        "arxiv_id\n" + "\n".join(selected_ids) + "\n"
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(raw_ids),
                "selected_total": len(selected_ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )


def test_run_stage_1_rejects_downselected_pool_after_shard(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()

    def fake_run_shards(run_dir, specs, **kwargs):
        _write_stage_1_contract_artifacts(run, raw_count=45, selected_count=40)

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    with pytest.raises(RuntimeError) as error:
        run_stage_1(run)

    assert "paper_pool.json must contain every paper kept by bulk search" in str(error.value)


def test_run_stage_1_validates_existing_primary_artifacts_before_skip(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    _write_stage_1_contract_artifacts(run, raw_count=45, selected_count=40)

    def fail_run_shards(*args, **kwargs):
        raise AssertionError("run_shards should not be called for existing primary artifacts")

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fail_run_shards)

    with pytest.raises(RuntimeError) as error:
        run_stage_1(run)

    assert "paper_pool.json must contain every paper kept by bulk search" in str(error.value)


def test_run_stage_2_chunks_paper_pool_into_weak_evidence_specs(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    ids = [f"2501.{idx:05d}" for idx in range(12)]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps({"reader_needed_concepts": ["concept"]}))

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_2(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [5, 5, 2]
    assert all(spec.agent == "weak_evidence_extractor" for spec in captured)
    assert all("Run Stage 2 only" in spec.prompt for spec in captured)
    assert all("arxiv_ids" in spec.prompt for spec in captured)


def test_run_stage_3_chunks_paper_pool_and_merges_weak_graph_fragments(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    ids = [f"2501.{idx:05d}" for idx in range(12)]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                arxiv_id = Path(rel_path).stem
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps(
                        {
                            "nodes": [
                                {"id": arxiv_id, "type": "Paper"},
                                {"id": "shared-method", "type": "Method"},
                            ],
                            "edges": [
                                {
                                    "src": arxiv_id,
                                    "dst": "shared-method",
                                    "type": "USES",
                                    "confidence": "weak",
                                }
                            ],
                        }
                    )
                )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_3(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [5, 5, 2]
    assert all(spec.agent == "weak_graph_extractor" for spec in captured)
    graph = json.loads((run / "05_weak_graph" / "weak_global_graph.json").read_text())
    assert len(graph["nodes"]) == 13
    assert len(graph["edges"]) == 12


def test_run_stage_4_dispatches_knowledge_base_reader(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        out = run_dir / "06_expansion" / "known_concepts_snapshot.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"known_concepts": []}))

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_4(run)

    assert len(captured) == 1
    assert captured[0].agent == "knowledge_base_reader"
    assert captured[0].expected_outputs == ["06_expansion/known_concepts_snapshot.json"]


def test_run_stage_5_dispatches_gap_detector_and_logs_queue_count(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        out_dir = run_dir / "06_expansion"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "knowledge_gap_report.json").write_text(json.dumps({"knowledge_gaps": []}))
        (out_dir / "expansion_need_queue.json").write_text(
            json.dumps({"items": [{"gap_id": "g1"}, {"gap_id": "g2"}]})
        )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_5(run)

    assert len(captured) == 1
    assert captured[0].agent == "knowledge_gap_detector"
    assert "queue_items=2" in (run / "run_log.csv").read_text()


def test_run_stage_6_writes_skipped_outputs_when_queue_is_empty(tmp_path):
    run = tmp_path / "run"
    (run / "06_expansion").mkdir(parents=True)
    (run / "06_expansion" / "expansion_need_queue.json").write_text(json.dumps({"items": []}))

    run_stage_6(run)

    assert json.loads((run / "06_expansion" / "expansion_round_01.json").read_text()) == {
        "items": [],
        "status": "skipped",
    }
    assert (run / "06_expansion" / "accepted_candidates.csv").read_text().startswith("arxiv_id,")
    assert (run / "06_expansion" / "rejected_candidates.csv").read_text().startswith("arxiv_id,")


def test_run_stage_6_dispatches_one_expansion_shard_per_gap_and_merges(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "06_expansion").mkdir(parents=True)
    (run / "06_expansion" / "expansion_need_queue.json").write_text(
        json.dumps({"items": [{"gap_id": "g1"}, {"gap_id": "g2"}]})
    )
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        expansion_dir = run_dir / "06_expansion"
        for spec in specs:
            shard_id = spec.shard_id
            (expansion_dir / f"expansion_round_01_shard_{shard_id}.json").write_text(
                json.dumps({"items": [{"shard_id": shard_id}]})
            )
            (expansion_dir / f"accepted_candidates_shard_{shard_id}.csv").write_text(
                "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
                f"2501.{shard_id[-3:]},g,{shard_id},Title,foundational,0.9,needed\n"
            )
            (expansion_dir / f"rejected_candidates_shard_{shard_id}.csv").write_text(
                "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
            )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_6(run, max_workers=20)

    assert [spec.shard_id for spec in captured] == ["expansion-001", "expansion-002"]
    assert all(spec.agent == "paper_expander" for spec in captured)
    round_data = json.loads((run / "06_expansion" / "expansion_round_01.json").read_text())
    assert round_data["status"] == "completed"
    assert len(round_data["items"]) == 2
    assert "2501.001" in (run / "06_expansion" / "accepted_candidates.csv").read_text()


def test_run_stage_7_dispatches_paper_ranker_and_validates_scores(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    ids = ["1.1", "1.2"]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend(specs)
        header = (
            "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
            "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
        )
        rows = "1.1,1,1,1,1,1,1,0,0.9\n1.2,0,0,0,0,0,0,0,0.1\n"
        (run / "07_scoring" / "paper_scores.csv").write_text(header + rows)
        (run / "07_scoring" / "promotion_candidates.csv").write_text(header + rows)
        (run / "07_scoring" / "promoted_papers.json").write_text(
            json.dumps({"promoted_papers": [{"arxiv_id": "1.1", "final_score": 0.9}]})
        )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_7(run)

    assert len(calls) == 1
    assert calls[0].agent == "paper_ranker"
    assert "Run Stage 7 scoring only" in calls[0].prompt
    assert "paper_scores.csv" in calls[0].prompt


def test_run_stage_7_normalizes_reduced_promotion_candidates_csv(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    ids = ["1.1", "1.2"]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id} for arxiv_id in ids])
    )

    def fake_run_shards(run_dir, specs, **kwargs):
        header = (
            "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
            "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
        )
        rows = "1.1,1,1,1,1,1,1,0,0.9\n1.2,0,0,0,0,0,0,0,0.1\n"
        (run / "07_scoring" / "paper_scores.csv").write_text(header + rows)
        (run / "07_scoring" / "promotion_candidates.csv").write_text(
            "arxiv_id,final_score,reason\n1.1,0.9,top\n1.2,0.1,tail\n"
        )
        (run / "07_scoring" / "promoted_papers.json").write_text(
            json.dumps(
                {
                    "promoted_papers": [
                        {"arxiv_id": "1.2", "final_score": 0.1, "reason": "tail"},
                        {"arxiv_id": "1.1", "final_score": 0.9, "reason": "top"},
                    ]
                }
            )
        )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_7(run)

    candidates = (run / "07_scoring" / "promotion_candidates.csv").read_text()
    promoted = json.loads((run / "07_scoring" / "promoted_papers.json").read_text())
    assert "topic_relevance" in candidates
    assert "reason" not in candidates.splitlines()[0]
    assert candidates.splitlines()[1].startswith("1.1,")
    assert promoted["promoted_papers"] == [{"arxiv_id": "1.1", "final_score": 0.9, "reason": "top"}]


def _write_promoted_papers(run, ids):
    (run / "07_scoring").mkdir(parents=True, exist_ok=True)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": arxiv_id} for arxiv_id in ids]})
    )


def test_run_stage_8_dispatches_full_markdown_fetch_for_promoted_papers(tmp_path, monkeypatch):
    run = tmp_path / "run"
    ids = ["1.1", "1.2"]
    _write_promoted_papers(run, ids)
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for rel_path in specs[0].expected_outputs:
            out = run_dir / rel_path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("# Paper\n")

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_8(run)

    assert len(captured) == 1
    assert captured[0].stage == "8"
    assert "Run Stage 8 full markdown fetch only" in captured[0].prompt
    assert captured[0].expected_outputs == [
        "08_full_markdown/1.1.md",
        "08_full_markdown/1.2.md",
    ]


def test_run_stage_9_shards_promoted_ids_and_requires_tree_and_nodes(tmp_path, monkeypatch):
    run = tmp_path / "run"
    ids = ["1.1", "1.2", "1.3"]
    _write_promoted_papers(run, ids)
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("{}")

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_9(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [4, 2]
    assert all(spec.agent == "paper_indexer" for spec in captured)
    assert "09_pageindex/nodes/1.1.nodes.json" in captured[0].expected_outputs


def test_run_stage_10_shards_one_paper_at_a_time_and_validates_grounding(tmp_path, monkeypatch):
    run = tmp_path / "run"
    ids = ["1.1", "1.2", "1.3"]
    _write_promoted_papers(run, ids)
    captured = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for rel_path in spec.expected_outputs:
                out = run_dir / rel_path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 2]}]})
                )

    monkeypatch.setattr("scripts.run_auto_research.run_shards", fake_run_shards)

    run_stage_10(run, max_workers=20)

    assert [len(spec.expected_outputs) for spec in captured] == [1, 1, 1]
    assert all(spec.agent == "verified_evidence_extractor" for spec in captured)
    assert all("Run Stage 10 only" in spec.prompt for spec in captured)


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

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)

    with (
        patch("scripts.run_auto_research.build_deterministic_stage_13_packs"),
        patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards),
    ):
        run_stage_13(run)

    assert [spec.shard_id for spec in captured] == ["pack-001", "pack-002"]
    assert captured[0].expected_outputs == [
        "13_chapter_packs/book/preface_pack.json",
        "13_chapter_packs/families/fam_a_pack.json",
    ]
    assert captured[1].expected_outputs == ["13_chapter_packs/methods/m1_pack.json"]
    assert "Execute directly in this codex exec session." in captured[0].prompt
    assert "Do not spawn subagents" in captured[0].prompt
    assert "do not run nested codex commands" in captured[0].prompt
    assert '"pack_targets": ["book:preface", "family:fam_a"]' in captured[0].prompt
    assert '"pack_targets": ["method:m1"]' in captured[1].prompt

    (run / "13_chapter_packs" / "book").mkdir(parents=True)
    (run / "13_chapter_packs" / "book" / "preface_pack.json").write_text("{}")
    captured.clear()
    with (
        patch("scripts.run_auto_research.build_deterministic_stage_13_packs"),
        patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards),
    ):
        run_stage_13(run)

    assert [spec.shard_id for spec in captured] == ["pack-001", "pack-002"]
    assert captured[0].expected_outputs == [
        "13_chapter_packs/book/preface_pack.json",
        "13_chapter_packs/families/fam_a_pack.json",
    ]


def test_build_deterministic_stage_13_packs_from_verified_evidence(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)

    result = build_deterministic_stage_13_packs(run)

    assert result == {"book": 1, "families": 1, "methods": 1, "skipped": 0}
    method_pack = json.loads(
        (run / "13_chapter_packs" / "methods" / "m1_pack.json").read_text()
    )
    assert method_pack["pack_type"] == "method"
    assert method_pack["method_id"] == "m1"
    assert method_pack["arxiv_id"] == "1.1"
    assert method_pack["structured"]["equations"] == [
        {
            "latex": "x = y",
            "purpose": "core equation",
            "symbols": [],
            "source_node_id": "s.02",
            "source_lines": [3, 4],
        }
    ]
    assert [section["section_title"] for section in method_pack["section_plan"]] == [
        "Summary",
        "Motivation",
        "Intuition",
        "Theory",
        "Algorithm",
        "Example",
        "Interpretation",
        "Strengths",
        "Limitations",
        "Software",
        "Related Methods",
    ]
    sections = {
        section["section_title"]: section["source_nodes"]
        for section in method_pack["section_plan"]
    }
    for required in ("Theory", "Algorithm", "Example", "Limitations"):
        assert sections[required]
        assert sections[required][0]["section_text"].strip()
        assert sections[required][0]["arxiv_id"] == "1.1"

    family_pack = json.loads(
        (run / "13_chapter_packs" / "families" / "fam_a_pack.json").read_text()
    )
    assert family_pack["pack_type"] == "family"
    assert family_pack["method_ids"] == [
        {"id": "m1", "title": "M1", "arxiv_id": "1.1"}
    ]
    assert family_pack["comparison_rows"][0]["source_node_id"] == "s.02"
    assert family_pack["data"]["method_ids"] == [
        {"id": "m1", "title": "M1", "arxiv_id": "1.1"}
    ]
    assert family_pack["data"]["comparison_rows"][0]["source_node_id"] == "s.02"

    book_pack = json.loads(
        (run / "13_chapter_packs" / "book" / "preface_pack.json").read_text()
    )
    assert book_pack["pack_type"] == "book"
    assert book_pack["section_id"] == "preface"
    assert book_pack["data"]["topic"] == "Fixture topic"


def test_build_method_pack_scopes_knowledge_gaps_to_method_evidence(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "10_verified_evidence").mkdir(parents=True)
    (run_dir / "06_expansion").mkdir(parents=True)
    (run_dir / "10_verified_evidence" / "1234.00001.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "text": "AudioMAE masks spectrogram patches before reconstruction.",
                        "claim_type": "method",
                        "source_node_id": "s.01",
                        "source_lines": [1, 3],
                    },
                    {
                        "text": "The encoder learns acoustic representations from mel spectrograms.",
                        "claim_type": "method",
                        "source_node_id": "s.02",
                        "source_lines": [4, 8],
                    },
                ],
                "equations": [],
                "algorithms": [],
                "limitations": [
                    {
                        "text": "The method depends on masked reconstruction quality.",
                        "source_node_id": "s.03",
                    }
                ],
            }
        )
    )
    (run_dir / "06_expansion" / "knowledge_gap_report.json").write_text(
        json.dumps(
            {
                "knowledge_gaps": [
                    {"concept": "asr", "priority": 0.9},
                    {"concept": "mel", "priority": 0.9},
                    {"concept": "mel spectrogram", "priority": 0.9},
                    {"concept": "masked reconstruction", "priority": 0.8},
                    {"concept": "codec tokens", "priority": 0.9},
                    {"concept": "full duplex dialog", "priority": 0.9},
                    {"concept": "autoregressive decoding", "priority": 0.9},
                ]
            }
        )
    )
    outline = {
        "families": [{"id": "fam", "title": "Fam", "method_ids": ["audiomae"]}],
        "methods": [
            {
                "id": "audiomae",
                "title": "AudioMAE",
                "arxiv_id": "1234.00001",
                "family_id": "fam",
                "neighbor_method_ids": [],
            }
        ],
    }

    pack = runner._build_method_pack(run_dir, outline, outline["methods"][0])

    assert pack["knowledge_gaps_to_explain"] == [
        "mel spectrogram",
        "masked reconstruction",
    ]
    assert "asr" not in pack["knowledge_gaps_to_explain"]
    assert "mel" not in pack["knowledge_gaps_to_explain"]


def test_run_stage_13_uses_deterministic_builder_before_codex_shards(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)

    with patch("scripts.run_auto_research.run_shards") as run_shards:
        run_stage_13(run)

    run_shards.assert_not_called()
    assert (run / "13_chapter_packs" / "book" / "preface_pack.json").exists()
    assert (run / "13_chapter_packs" / "families" / "fam_a_pack.json").exists()
    assert (run / "13_chapter_packs" / "methods" / "m1_pack.json").exists()


def test_build_deterministic_stage_13_reads_wrapped_pageindex_nodes(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run, wrap_nodes=True)

    build_deterministic_stage_13_packs(run)

    method_pack = json.loads(
        (run / "13_chapter_packs" / "methods" / "m1_pack.json").read_text()
    )
    theory_nodes = [
        section["source_nodes"]
        for section in method_pack["section_plan"]
        if section["section_title"] == "Theory"
    ][0]
    assert theory_nodes[0]["section_title"] == "Method"
    assert theory_nodes[0]["section_text"] == "## Method\nThe method uses x = y to update state.\n"


def test_build_deterministic_stage_13_does_not_write_invalid_method_pack(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run, omit_required_specific_sources=True)

    result = build_deterministic_stage_13_packs(run)

    assert result == {"book": 1, "families": 1, "methods": 0, "skipped": 0}
    assert not (run / "13_chapter_packs" / "methods" / "m1_pack.json").exists()


def test_build_deterministic_stage_13_falls_back_to_method_claims_for_theory_and_algorithm(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)
    evidence_path = run / "10_verified_evidence" / "1.1.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["equations"] = []
    evidence["algorithms"] = []
    evidence_path.write_text(json.dumps(evidence))

    result = build_deterministic_stage_13_packs(run)

    assert result["methods"] == 1
    method_pack = json.loads((run / "13_chapter_packs" / "methods" / "m1_pack.json").read_text())
    sections = {
        section["section_title"]: section["source_nodes"]
        for section in method_pack["section_plan"]
    }
    assert sections["Theory"][0]["node_id"] == "s.02"
    assert sections["Algorithm"][0]["node_id"] == "s.02"
    assert sections["Theory"][0]["section_text"].strip()
    assert sections["Algorithm"][0]["section_text"].strip()


def test_build_deterministic_stage_13_repairs_invalid_existing_method_pack(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    _write_stage_13_sources(run)
    invalid_pack = run / "13_chapter_packs" / "methods" / "m1_pack.json"
    invalid_pack.parent.mkdir(parents=True, exist_ok=True)
    invalid_pack.write_text(
        json.dumps({"pack_type": "method", "method_id": "m1", "section_plan": []})
    )

    result = build_deterministic_stage_13_packs(run)

    assert result["methods"] == 1
    repaired = json.loads(invalid_pack.read_text())
    assert [section["section_title"] for section in repaired["section_plan"]] == [
        "Summary",
        "Motivation",
        "Intuition",
        "Theory",
        "Algorithm",
        "Example",
        "Interpretation",
        "Strengths",
        "Limitations",
        "Software",
        "Related Methods",
    ]
    assert all(
        section["source_nodes"][0]["section_text"].strip()
        for section in repaired["section_plan"]
        if section["section_title"] in {"Theory", "Algorithm", "Example", "Limitations"}
    )


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

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
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
    assert '"section_ids": ["preface", "goals"]' in captured[0].prompt
    assert '"family_ids": ["fam_a"]' in captured[1].prompt
    assert '"method_ids": ["m1"]' in captured[2].prompt


def test_run_stage_14_shards_methods_one_at_a_time(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        methods=[
            {"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"},
            {"id": "m2", "title": "M2", "arxiv_id": "2.2", "family_id": "fam_a"},
            {"id": "m3", "title": "M3", "arxiv_id": "3.3", "family_id": "fam_a"},
        ],
    )
    captured = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_14(run)

    method_specs = [spec for spec in captured if spec.agent == "method_chapter_writer"]
    assert [(spec.shard_id, spec.expected_outputs) for spec in method_specs] == [
        ("write-methods-001", ["14_chapters/methods/m1.md"]),
        ("write-methods-002", ["14_chapters/methods/m2.md"]),
        ("write-methods-003", ["14_chapters/methods/m3.md"]),
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


def test_run_stage_15_uses_typed_chapter_targets_in_prompt(tmp_path):
    run = tmp_path / "run"
    _write_outline(run)
    captured = []

    def fake_run_shards(run_dir, specs, max_retries=1, **kwargs):
        captured.extend(specs)
        for spec in specs:
            for relpath in spec.expected_outputs:
                path = run / relpath
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "passed": True,
                            "summary": {
                                "claims_total": 0,
                                "claims_unsupported": 0,
                                "claims_overstated": 0,
                                "gaps_covered": 0,
                                "gaps_missing": 0,
                                "word_count": 1500,
                                "form_issue_count": 0,
                                "equations_rendered": 0,
                                "pseudocode_blocks": 0,
                            },
                        }
                    )
                )

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_15(run)

    assert len(captured) == 2
    assert '"chapter_targets": ["book:preface", "family:fam_a"]' in captured[0].prompt
    assert '"chapter_targets": ["method:m1"]' in captured[1].prompt


def test_run_stage_15_repairs_blocking_form_issues_once(tmp_path):
    run = tmp_path / "run"
    (run / "12_taxonomy").mkdir(parents=True)
    (run / "12_taxonomy" / "outline.json").write_text(
        json.dumps(
            {
                "topic": "Fixture topic",
                "book_sections": [{"id": "preface", "title": "Preface"}],
                "families": [],
                "methods": [],
            }
        )
    )
    calls = []

    def fake_run_shards(run_dir, specs, **kwargs):
        calls.extend((spec.agent, spec.prompt, spec.expected_outputs) for spec in specs)
        for spec in specs:
            if spec.agent == "verifier":
                passed = len([call for call in calls if call[0] == "verifier"]) > 1
                path = run / "15_verification" / "book" / "preface_verification.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "passed": passed,
                            "form_issues": []
                            if passed
                            else [
                                {
                                    "check": "chapter_file_missing",
                                    "detail": "Missing chapter file.",
                                    "excerpt": "",
                                }
                            ],
                            "summary": {
                                "claims_total": 0,
                                "claims_unsupported": 0,
                                "claims_overstated": 0,
                                "gaps_covered": 0,
                                "gaps_missing": 0,
                                "word_count": 600 if passed else 0,
                                "form_issue_count": 0 if passed else 1,
                                "equations_rendered": 0,
                                "pseudocode_blocks": 0,
                            },
                        }
                    )
                )
            else:
                path = run / "14_chapters" / "book" / "00_preface.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Preface\n\n" + "word " * 600)

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_15(run)

    assert [call[0] for call in calls] == [
        "verifier",
        "book_section_writer",
        "verifier",
    ]
    assert '"form_issues": {"preface": [{"check": "chapter_file_missing"' in calls[1][1]
    summary = (run / "15_verification" / "verification_summary.csv").read_text()
    assert "book,preface,True" in summary


def test_run_stage_16_builds_manifest_deterministically_in_canonical_order(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        book_sections=[
            {"id": "preface", "title": "Preface"},
            {"id": "goals", "title": "Goals"},
        ],
    )
    for target in build_chapter_targets(run):
        chapter_path = run / {
            "book": f"14_chapters/book/{'00_preface.md' if target['id'] == 'preface' else '03_goals.md'}",
            "families": f"14_chapters/families/{target['id']}.md",
            "methods": f"14_chapters/methods/{target['id']}.md",
        }[target["type"]]
        chapter_path.parent.mkdir(parents=True, exist_ok=True)
        chapter_path.write_text(f"# {target['id']}\n\nBody text.\n")
        verification_path = run / "15_verification" / target["type"] / f"{target['id']}_verification.json"
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(
            json.dumps(
                {
                    "passed": True,
                    "summary": {
                        "word_count": 1500,
                        "form_issue_count": 0,
                        "equations_rendered": 0,
                        "pseudocode_blocks": 0,
                    },
                }
            )
        )

    with patch("scripts.run_auto_research.run_shards") as run_shards:
        run_stage_16(run)

    run_shards.assert_not_called()
    manifest = json.loads((run / "16_book" / "chapters_manifest.json").read_text())
    assert [chapter["chapter_id"] for chapter in manifest["chapters"]] == [
        "preface",
        "goals",
        "fam_a",
        "m1",
    ]
    assert all(chapter["status"] == "passed" for chapter in manifest["chapters"])
    assert (run / "14_chapters" / "methods" / "m1.md").read_text().startswith("---\n")
    assert not list((run / "16_book").glob("chapters_manifest_shard_*.json"))


def test_run_stage_16_treats_high_word_count_as_non_blocking(tmp_path):
    run = tmp_path / "run"
    _write_outline(
        run,
        methods=[
            {"id": "m_long", "title": "Long Method", "arxiv_id": "1.1", "family_id": "fam_a"},
            {"id": "m_bad", "title": "Bad Method", "arxiv_id": "2.2", "family_id": "fam_a"},
        ],
    )
    verification_by_id = {
        "preface": {"passed": True, "summary": {"word_count": 600, "form_issue_count": 0}},
        "fam_a": {"passed": True, "summary": {"word_count": 1200, "form_issue_count": 0}},
        "m_long": {
            "passed": False,
            "form_issues": [
                {
                    "check": "method_word_count_high",
                    "detail": "Method chapter has 4200 words; maximum is 3000.",
                    "excerpt": "# Long Method",
                }
            ],
            "summary": {
                "word_count": 4200,
                "form_issue_count": 1,
                "claims_unsupported": 0,
                "claims_overstated": 0,
                "gaps_missing": 0,
            },
        },
        "m_bad": {
            "passed": False,
            "form_issues": [
                {
                    "check": "copied_source_outline",
                    "detail": "Copied source headings into the chapter.",
                    "excerpt": "Baselines.",
                }
            ],
            "summary": {
                "word_count": 2200,
                "form_issue_count": 1,
                "claims_unsupported": 0,
                "claims_overstated": 0,
                "gaps_missing": 0,
            },
        },
    }
    for target in build_chapter_targets(run):
        chapter_path = run / {
            "book": "14_chapters/book/00_preface.md",
            "families": f"14_chapters/families/{target['id']}.md",
            "methods": f"14_chapters/methods/{target['id']}.md",
        }[target["type"]]
        chapter_path.parent.mkdir(parents=True, exist_ok=True)
        chapter_path.write_text(f"# {target['id']}\n\nDetailed chapter body.\n")
        verification_path = run / "15_verification" / target["type"] / f"{target['id']}_verification.json"
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(json.dumps(verification_by_id[target["id"]]))

    run_stage_16(run)

    manifest = json.loads((run / "16_book" / "chapters_manifest.json").read_text())
    statuses = {chapter["chapter_id"]: chapter["status"] for chapter in manifest["chapters"]}
    assert statuses["m_long"] == "passed"
    assert statuses["m_bad"] == "excluded_form_issues"


def test_verification_status_accepts_summary_passed_for_backward_compat():
    target = {"type": "families", "id": "evaluation_benchmarks"}
    verification = {
        "summary": {
            "passed": True,
            "claims_unsupported": 0,
            "claims_overstated": 0,
            "gaps_missing": 0,
            "form_issue_count": 0,
            "word_count": 1400,
        }
    }

    status, reason = runner._verification_status(
        target,
        verification,
        chapter_word_count=1400,
    )

    assert status == "passed"
    assert reason == ""


def test_verification_status_prefers_explicit_top_level_failed_flag():
    target = {"type": "families", "id": "evaluation_benchmarks"}
    verification = {
        "passed": False,
        "summary": {
            "passed": True,
            "claims_unsupported": 0,
            "claims_overstated": 0,
            "gaps_missing": 0,
            "form_issue_count": 0,
            "word_count": 1400,
        },
    }

    status, reason = runner._verification_status(
        target,
        verification,
        chapter_word_count=1400,
    )

    assert status == "excluded_verification_failed"
    assert reason == "verification did not pass"


def _write_outline(run, *, book_sections=None, methods=None):
    (run / "12_taxonomy").mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "Fixture topic",
        "book_sections": book_sections
        or [
            {"id": "preface", "title": "Preface"},
            {"id": "appendices", "title": "Appendices"},
        ],
        "families": [{"id": "fam_a", "title": "A", "method_ids": ["m1"]}],
        "methods": methods
        or [{"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"}],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))


def _write_stage_13_sources(run, *, wrap_nodes=False, omit_required_specific_sources=False):
    (run / "00_input").mkdir(parents=True, exist_ok=True)
    (run / "00_input" / "topic.md").write_text("# Fixture topic\n")
    (run / "06_expansion").mkdir(parents=True, exist_ok=True)
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text(
        json.dumps({"known_concepts": [{"id": "accuracy", "definition": "Correctness."}]})
    )
    (run / "06_expansion" / "knowledge_gap_report.json").write_text(
        json.dumps({"knowledge_gaps": [{"name": "latent reasoning"}]})
    )
    (run / "10_verified_evidence").mkdir(parents=True, exist_ok=True)
    (run / "10_verified_evidence" / "1.1.json").write_text(
        json.dumps(
            {
                "arxiv_id": "1.1",
                "title": "Fixture Paper",
                "year": 2026,
                "claims": [
                    {
                        "text": "The method solves the fixture problem.",
                        "source_node_id": "s.01",
                        "source_lines": [1, 2],
                        "claim_type": "motivation",
                        "confidence": "high",
                    },
                    {
                        "text": "The algorithm applies the equation to update state.",
                        "source_node_id": "s.02",
                        "source_lines": [3, 4],
                        "claim_type": "method",
                        "confidence": "high",
                    },
                ]
                + (
                    []
                    if omit_required_specific_sources
                    else [
                        {
                            "text": "The evaluation uses a small worked example.",
                            "source_node_id": "s.03",
                            "source_lines": [5, 6],
                            "claim_type": "result",
                            "confidence": "high",
                        },
                        {
                            "text": "The method is limited by noisy supervision.",
                            "source_node_id": "s.04",
                            "source_lines": [7, 8],
                            "claim_type": "limitation",
                            "confidence": "high",
                        },
                    ]
                ),
                "equations": []
                if omit_required_specific_sources
                else [
                    {
                        "latex": "x = y",
                        "purpose": "core equation",
                        "symbols": [],
                        "source_node_id": "s.02",
                        "source_lines": [3, 4],
                    }
                ],
                "algorithms": []
                if omit_required_specific_sources
                else [
                    {
                        "name": "Fixture update",
                        "pseudocode": "state <- update(state)",
                        "steps": ["Read state", "Update state", "Return state"],
                        "source_node_id": "s.02",
                        "source_lines": [3, 4],
                    }
                ],
                "hyperparameters": []
                if omit_required_specific_sources
                else [
                    {"name": "steps", "value": "3", "purpose": "depth", "source_node_id": "s.03"}
                ],
                "complexity": [
                    {"text": "Linear in sequence length.", "regime": "inference", "source_node_id": "s.02"}
                ],
                "datasets": [{"name": "FixtureSet", "source_node_id": "s.03"}],
                "limitations": []
                if omit_required_specific_sources
                else [
                    {"text": "Noisy supervision can hurt.", "source_node_id": "s.04", "source_lines": [7, 8]}
                ],
                "neighbors": [],
            }
        )
    )
    (run / "09_pageindex" / "nodes").mkdir(parents=True, exist_ok=True)
    nodes = {
        "s.01": {"id": "s.01", "title": "Introduction", "start_line": 1, "end_line": 2},
        "s.02": {"id": "s.02", "title": "Method", "start_line": 3, "end_line": 4},
        "s.03": {"id": "s.03", "title": "Experiments", "start_line": 5, "end_line": 6},
        "s.04": {"id": "s.04", "title": "Limitations", "start_line": 7, "end_line": 8},
    }
    if wrap_nodes:
        nodes_payload = {"arxiv_id": "1.1", "nodes": nodes}
    else:
        nodes_payload = nodes
    (run / "09_pageindex" / "nodes" / "1.1.nodes.json").write_text(
        json.dumps(nodes_payload)
    )
    (run / "08_full_markdown").mkdir(parents=True, exist_ok=True)
    (run / "08_full_markdown" / "1.1.md").write_text(
        "\n".join(
            [
                "## Introduction",
                "The fixture problem motivates the method.",
                "## Method",
                "The method uses x = y to update state.",
                "## Experiments",
                "A worked example uses three update steps.",
                "## Limitations",
                "Noisy supervision can hurt the method.",
            ]
        )
        + "\n"
    )


def _skip_stage_1_start_preflight(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_auto_research._validate_stage_1_before_later_start",
        lambda run_dir, start: None,
    )


def test_main_resume_from_stage_11_calls_stage_11(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
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


def test_main_all_resume_from_stage_7_includes_bootstrap_handlers(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    monkeypatch.setattr("scripts.run_auto_research.run_stage_7", lambda run_dir: calls.append("7"))
    monkeypatch.setattr("scripts.run_auto_research.run_stage_8", lambda run_dir: calls.append("8"))
    monkeypatch.setattr("scripts.run_auto_research.run_stage_9", lambda run_dir: calls.append("9"))
    monkeypatch.setattr("scripts.run_auto_research.run_stage_10", lambda run_dir: calls.append("10"))
    monkeypatch.setattr("scripts.run_auto_research.run_stage_11", lambda run_dir: calls.append("11"))
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_13", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_14", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_15", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_16", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_17", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_18", lambda run_dir: None)

    rc = main(["--run-id", "demo", "--phase", "all", "--resume", "--from-stage", "7"])

    assert rc == 0
    assert calls[:5] == ["7", "8", "9", "10", "11"]


def test_main_resume_from_stage_7_validates_stage_1_keep_all_contract(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    _write_valid_bootstrap_contract(run)
    kept_ids = [f"2501.{idx:05d}" for idx in range(200)]
    selected_ids = kept_ids[:50]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps(
            [{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in selected_ids]
        )
    )
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    calls = []
    monkeypatch.setattr("scripts.run_auto_research.run_stage_7", lambda run_dir: calls.append("7"))

    with pytest.raises(RuntimeError, match="paper_pool.json must contain every paper kept"):
        main(["--run-id", "demo", "--phase", "all", "--resume", "--from-stage", "7"])

    assert calls == []


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
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    for stage in ("14", "15", "16", "17", "18"):
        monkeypatch.setattr(
            f"scripts.run_auto_research.run_stage_{stage}",
            lambda run_dir, stage=stage: calls.append(stage),
        )

    rc = main(["--run-id", "demo", "--phase", "write"])

    assert rc == 0
    assert calls == ["14", "15", "16", "17", "18"]


def test_main_write_phase_passes_max_workers_20_to_parallel_stages(tmp_path, monkeypatch):
    run = tmp_path / "research_runs" / "demo"
    run.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)
    calls = []

    def fake_parallel_stage(run_dir, *, max_workers=1):
        calls.append(max_workers)

    monkeypatch.setattr("scripts.run_auto_research.run_stage_14", fake_parallel_stage)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_15", fake_parallel_stage)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_16", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_17", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_18", lambda run_dir: None)

    rc = main(["--run-id", "demo", "--phase", "write", "--max-workers", "20"])

    assert rc == 0
    assert calls == [20, 20]


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


def test_main_with_topic_starts_new_run_before_requested_stage(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    _skip_stage_1_start_preflight(monkeypatch)

    def fake_start_run(topic, phase):
        run = tmp_path / "research_runs" / "demo-run"
        run.mkdir(parents=True)
        return "demo-run"

    monkeypatch.setattr("scripts.run_auto_research.start_new_run", fake_start_run)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_11", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_12_5", lambda run_dir: None)
    monkeypatch.setattr("scripts.run_auto_research.run_stage_13", lambda run_dir: None)

    rc = main(["--topic", "Demo topic", "--phase", "draft", "--from-stage", "11"])

    assert rc == 0
    assert (tmp_path / "research_runs" / "demo-run" / "run_control" / "run_state.json").exists()


def test_main_topic_all_uses_stage_scoped_bootstrap_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    calls = []

    def fake_start_run(topic, phase):
        run = tmp_path / "research_runs" / "demo-run"
        run.mkdir(parents=True)
        calls.append(("0", topic, phase))
        return "demo-run"

    def fake_stage(stage):
        def run(run_dir, **kwargs):
            calls.append((stage, run_dir.name))

        return run

    monkeypatch.setattr("scripts.run_auto_research.start_new_run", fake_start_run)
    for stage in (
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "12.5",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ):
        monkeypatch.setattr(
            f"scripts.run_auto_research.run_stage_{stage.replace('.', '_')}",
            fake_stage(stage),
        )

    rc = main(["--topic", "Demo topic", "--phase", "all", "--executor", "sdk", "--max-workers", "20"])

    assert rc == 0
    assert calls[:11] == [
        ("0", "Demo topic", "all"),
        ("1", "demo-run"),
        ("2", "demo-run"),
        ("3", "demo-run"),
        ("4", "demo-run"),
        ("5", "demo-run"),
        ("6", "demo-run"),
        ("7", "demo-run"),
        ("8", "demo-run"),
        ("9", "demo-run"),
        ("10", "demo-run"),
    ]


def _write_valid_bootstrap_contract(run, ids=None):
    if ids is None:
        ids = [f"2501.{idx:05d}" for idx in range(200)]
    (run / "00_input").mkdir(parents=True)
    (run / "01_seed_pool").mkdir(parents=True)
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "04_weak_evidence").mkdir(parents=True)
    (run / "07_scoring").mkdir(parents=True)
    (run / "08_full_markdown").mkdir(parents=True)
    (run / "09_pageindex" / "trees").mkdir(parents=True)
    (run / "10_verified_evidence").mkdir(parents=True)

    aspects = [
        {
            "id": f"aspect_{idx}",
            "normal_queries": [f"normal query {idx}"],
            "survey_queries": [f"survey query {idx}"],
            "positive_keywords": [f"keyword {idx}"],
        }
        for idx in range(4)
    ]
    (run / "00_input" / "search_plan.json").write_text(
        json.dumps({"aspects": aspects})
    )
    bulk_path = run / "01_seed_pool" / "bulk_search_results_123.json"
    bulk_path.write_text(json.dumps({arxiv_id: "abstract" for arxiv_id in ids}))
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": {arxiv_id: "abstract" for arxiv_id in ids},
                "total_kept": len(ids),
                "output_path": str(bulk_path),
            }
        )
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in ids])
    )
    (run / "02_paper_pool" / "paper_pool.csv").write_text(
        "arxiv_id\n" + "\n".join(ids) + "\n"
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(ids),
                "selected_total": len(ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )
    for arxiv_id in ids:
        (run / "04_weak_evidence" / f"{arxiv_id}.json").write_text(
            json.dumps({"reader_needed_concepts": ["concept"]})
        )
    promoted_id = ids[0]
    score_header = (
        "arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,"
        "implementation_impact,chapter_need,knowledge_gap_boost,final_score\n"
    )
    score_rows = "".join(
        f"{arxiv_id},0.8,0.5,0.2,0.8,0.5,0.5,0.0,{0.9 if arxiv_id == promoted_id else 0.1}\n"
        for arxiv_id in ids
    )
    (run / "07_scoring" / "paper_scores.csv").write_text(score_header + score_rows)
    (run / "07_scoring" / "promotion_candidates.csv").write_text(score_header + score_rows)
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": promoted_id, "final_score": 0.9}]})
    )
    (run / "08_full_markdown" / f"{promoted_id}.md").write_text("# Paper\n")
    (run / "09_pageindex" / "trees" / f"{promoted_id}.tree.json").write_text("{}")
    (run / "10_verified_evidence" / f"{promoted_id}.json").write_text(
        json.dumps({"claims": [{"source_node_id": "s.01", "source_lines": [1, 1]}]})
    )


def test_validate_bootstrap_contract_requires_real_bulk_search_artifact(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps({"papers": {"2501.00000": "abstract"}})
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "output_path" in str(error)
    else:
        raise AssertionError("expected missing bulk output_path failure")


def test_validate_bootstrap_contract_rejects_too_many_search_aspects(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    aspects = [
        {
            "id": f"aspect_{idx}",
            "normal_queries": [f"normal query {idx}"],
            "survey_queries": [f"survey query {idx}"],
            "positive_keywords": [f"keyword {idx}"],
        }
        for idx in range(9)
    ]
    (run / "00_input" / "search_plan.json").write_text(json.dumps({"aspects": aspects}))

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "4..8 aspects" in str(error)
    else:
        raise AssertionError("expected too many aspects failure")


def test_validate_bootstrap_contract_rejects_tiny_paper_pool(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    tiny_ids = [f"2501.{idx:05d}" for idx in range(3)]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in tiny_ids])
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "at least 40 papers" in str(error)
    else:
        raise AssertionError("expected tiny paper pool failure")


def test_validate_bootstrap_contract_rejects_truncated_large_seed_pool(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    kept_ids = [f"2501.{idx:05d}" for idx in range(220)]
    selected_ids = kept_ids[:50]
    (run / "01_seed_pool" / "bulk_search_results_123.json").write_text(
        json.dumps({arxiv_id: "abstract" for arxiv_id in kept_ids})
    )
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": {arxiv_id: "abstract" for arxiv_id in kept_ids},
                "total_kept": len(kept_ids),
                "output_path": str(run / "01_seed_pool" / "bulk_search_results_123.json"),
            }
        )
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"} for arxiv_id in selected_ids])
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(kept_ids),
                "target_seed_papers": 200,
                "selected_total": len(selected_ids),
                "per_aspect_selected": {f"aspect_{idx}": 10 for idx in range(4)},
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_pool.json must contain every paper kept by bulk search" in str(error)
    else:
        raise AssertionError("expected truncated large seed pool failure")


def test_validate_bootstrap_contract_requires_candidate_pool_report(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    (run / "02_paper_pool" / "candidate_pool_report.json").unlink()

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "candidate_pool_report.json" in str(error)
    else:
        raise AssertionError("expected missing candidate pool report failure")


def test_validate_bootstrap_contract_accepts_real_discovery_shape(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)

    validate_bootstrap_stage_0_10_contract(run)


def test_validate_stage_1_keep_all_contract_requires_pool_csv_matches_json(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    csv_ids = ids[:-1] + ["2502.99999"]
    (run / "02_paper_pool" / "paper_pool.csv").write_text(
        "arxiv_id\n" + "\n".join(csv_ids) + "\n"
    )

    with pytest.raises(RuntimeError) as error:
        validate_stage_1_keep_all_contract(run)

    assert "paper_pool.csv must contain exactly every paper_pool arxiv_id" in str(error.value)


def test_validate_stage_1_keep_all_contract_rejects_bulk_output_mismatch(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    (run / "01_seed_pool" / "bulk_search_results_123.json").write_text(
        json.dumps({arxiv_id: "abstract" for arxiv_id in ids + ["2502.99999"]})
    )

    with pytest.raises(RuntimeError) as error:
        validate_stage_1_keep_all_contract(run)

    assert "bulk_search_results artifact must match seed_pool_raw.json papers" in str(error.value)


def test_validate_stage_1_keep_all_contract_requires_query_fields_per_aspect(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    search_plan_path = run / "00_input" / "search_plan.json"
    search_plan = json.loads(search_plan_path.read_text())
    search_plan["aspects"][0]["survey_queries"] = []
    search_plan_path.write_text(json.dumps(search_plan))

    with pytest.raises(RuntimeError) as error:
        validate_stage_1_keep_all_contract(run)

    assert "must include non-empty normal_queries, survey_queries, and positive_keywords" in str(error.value)


def test_validate_bootstrap_contract_rejects_duplicate_raw_seed_ids(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    duplicate_raw_ids = ids + [ids[0]]
    (run / "01_seed_pool" / "seed_pool_raw.json").write_text(
        json.dumps(
            {
                "papers": duplicate_raw_ids,
                "total_kept": len(duplicate_raw_ids),
                "output_path": str(run / "01_seed_pool" / "bulk_search_results_123.json"),
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "seed_pool_raw.json papers must not contain duplicate arxiv_id" in str(error)
    else:
        raise AssertionError("expected duplicate raw seed failure")


def test_validate_bootstrap_contract_rejects_duplicate_paper_pool_ids(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(40)]
    _write_valid_bootstrap_contract(run, ids=ids)
    duplicate_pool_ids = ids + [ids[0]]
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps(
            [
                {"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"}
                for arxiv_id in duplicate_pool_ids
            ]
        )
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(ids),
                "selected_total": len(duplicate_pool_ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_pool.json must not contain duplicate arxiv_id" in str(error)
    else:
        raise AssertionError("expected duplicate paper pool failure")


def test_validate_bootstrap_contract_ignores_legacy_target_seed_papers(tmp_path):
    run = tmp_path / "run"
    ids = [f"2501.{idx:05d}" for idx in range(60)]
    _write_valid_bootstrap_contract(run, ids=ids)
    search_plan = json.loads((run / "00_input" / "search_plan.json").read_text())
    search_plan["target_seed_papers"] = 40
    (run / "00_input" / "search_plan.json").write_text(json.dumps(search_plan))

    validate_bootstrap_stage_0_10_contract(run)


def test_validate_bootstrap_contract_rejects_missing_raw_seed_paper(tmp_path):
    run = tmp_path / "run"
    raw_ids = [f"2501.{idx:05d}" for idx in range(60)]
    selected_ids = raw_ids[:-1] + ["2502.99999"]
    _write_valid_bootstrap_contract(run, ids=raw_ids)
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps(
            [
                {"arxiv_id": arxiv_id, "title": f"Paper {arxiv_id}"}
                for arxiv_id in selected_ids
            ]
        )
    )
    (run / "02_paper_pool" / "candidate_pool_report.json").write_text(
        json.dumps(
            {
                "raw_kept": len(raw_ids),
                "selected_total": len(selected_ids),
                "selection_policy": "keep_all_bulk_search_results",
                "per_aspect_selected": {},
            }
        )
    )

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_pool.json must contain every paper kept by bulk search" in str(error)
    else:
        raise AssertionError("expected missing raw seed paper failure")


def test_validate_bootstrap_contract_rejects_stage7_without_score_files(tmp_path):
    run = tmp_path / "run"
    _write_valid_bootstrap_contract(run)
    (run / "07_scoring" / "paper_scores.csv").unlink()
    (run / "07_scoring" / "promotion_candidates.csv").unlink()

    try:
        validate_bootstrap_stage_0_10_contract(run)
    except RuntimeError as error:
        assert "paper_scores.csv" in str(error)
    else:
        raise AssertionError("expected missing Stage 7 score files failure")


def test_bootstrap_new_run_is_retired():
    try:
        bootstrap_new_run("Demo topic", "all")
    except RuntimeError as error:
        assert "retired" in str(error)
    else:
        raise AssertionError("expected retired bootstrap failure")


def test_main_status_reports_failed_sdk_thread(tmp_path, monkeypatch, capsys):
    run = tmp_path / "research_runs" / "demo"
    shard_dir = run / "run_control" / "stages" / "14" / "shards"
    shard_dir.mkdir(parents=True)
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")
    save_run_state(
        run,
        {
            "run_id": "demo",
            "phase": "write",
            "status": "failed",
            "current_stage": "14",
        },
    )
    (run / "run_log.csv").write_text(
        "timestamp,stage,status,detail\n2026-01-01T00:00:00+00:00,14,failed,write-001 missing expected outputs\n"
    )
    (shard_dir / "write-001.attempt-1.stderr.txt").write_text("bad chapter\n")
    (shard_dir / "write-001.json").write_text(
        json.dumps(
            {
                "stage": "14",
                "shard_id": "write-001",
                "status": "failed",
                "executor": "sdk",
                "thread_id": "thread-123",
                "turn_id": "turn-456",
                "stderr_path": "run_control/stages/14/shards/write-001.attempt-1.stderr.txt",
            }
        )
    )

    rc = main(["--run-id", "demo", "--status"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "run_id=demo" in out
    assert "status=failed" in out
    assert "failed_stage=14" in out
    assert "failed_shard=write-001" in out
    assert "thread_id=thread-123" in out
    assert "turn_id=turn-456" in out
    assert "stderr=run_control/stages/14/shards/write-001.attempt-1.stderr.txt" in out


def test_main_rejects_topic_write_phase():
    try:
        main(["--topic", "Demo topic", "--phase", "write"])
    except SystemExit as error:
        assert "--topic cannot be used with --phase write" in str(error)
    else:
        raise AssertionError("expected topic write phase failure")


def test_main_rejects_unsafe_cli_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.run_auto_research.RUNS_ROOT", tmp_path / "research_runs")

    try:
        main(["--run-id", "../escape", "--phase", "draft"])
    except ValueError as error:
        assert "unsafe run_id" in str(error)
    else:
        raise AssertionError("expected unsafe CLI run_id failure")
