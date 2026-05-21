import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.auto_research_runner.stages import run_stage_5, run_stage_17

FIXTURE = Path(__file__).parent / "fixtures" / "weak_graph_mini"


@pytest.fixture
def run_dir(tmp_path):
    dest = tmp_path / "run"
    dest.mkdir()
    for sub in ("05_weak_graph", "04_weak_evidence", "06_expansion"):
        (dest / sub).mkdir()
    shutil.copy(
        FIXTURE / "weak_global_graph.json",
        dest / "05_weak_graph" / "weak_global_graph.json",
    )
    for f in (FIXTURE / "04_weak_evidence").iterdir():
        shutil.copy(f, dest / "04_weak_evidence" / f.name)
    (dest / "06_expansion" / "known_concepts_snapshot.json").write_text(
        (FIXTURE / "known_concepts_snapshot.json").read_text()
    )
    (dest / "run_log.csv").write_text("stage,status,detail\n")
    return dest


def test_run_stage_5_dispatches_classifier(run_dir):
    captured = []

    def fake_run_shards(_run_dir, specs, *, executor, force=False):
        captured.extend(specs)
        out = _run_dir / "06_expansion"
        digest = json.loads((out / "gap_candidates_digest.json").read_text())
        concept = digest["candidates"][0]["concept"]
        (out / "knowledge_gap_report.json").write_text(
            json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": [
                {"concept": concept}
            ]})
        )
        (out / "expansion_need_queue.json").write_text(
            json.dumps({"items": [{
                "gap_id": "gap_1",
                "concept": concept,
                "priority": 0.70,
                "search_queries": [f"{concept} arxiv", f"{concept} survey"],
            }]})
        )
        (out / "extracted_concepts.json").write_text(
            json.dumps({"concepts": [{"concept": concept, "bucket": "knowledge_gap"}]})
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_5(run_dir)

    assert (run_dir / "06_expansion" / "gap_candidates_digest.json").exists()
    assert len(captured) == 1
    assert captured[0].agent == "knowledge_gap_classifier"
    assert "06_expansion/extracted_concepts.json" in captured[0].expected_outputs
    assert (run_dir / "06_expansion" / "stage5_metadata.json").exists()


def test_run_stage_5_reruns_old_detector_artifacts_without_metadata(run_dir):
    out = run_dir / "06_expansion"
    (out / "knowledge_gap_report.json").write_text(
        json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": []})
    )
    (out / "expansion_need_queue.json").write_text(
        json.dumps({"items": []})
    )
    captured = []

    def fake_run_shards(_run_dir, specs, *, executor, force=False):
        captured.append((specs[0], force))
        digest = json.loads((out / "gap_candidates_digest.json").read_text())
        concept = digest["candidates"][0]["concept"]
        (out / "knowledge_gap_report.json").write_text(
            json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": [
                {"concept": concept}
            ]})
        )
        (out / "expansion_need_queue.json").write_text(
            json.dumps({"items": [{
                "gap_id": "gap_1",
                "concept": concept,
                "priority": 0.70,
                "search_queries": [f"{concept} arxiv", f"{concept} survey"],
            }]})
        )
        (out / "extracted_concepts.json").write_text(
            json.dumps({"concepts": [{"concept": concept, "bucket": "knowledge_gap"}]})
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_5(run_dir)

    assert len(captured) == 1
    assert captured[0][0].agent == "knowledge_gap_classifier"
    assert captured[0][1] is True


def test_run_stage_5_idempotent_when_metadata_matches(run_dir):
    def fake_run_shards(_run_dir, specs, *, executor, force=False):
        out = _run_dir / "06_expansion"
        digest = json.loads((out / "gap_candidates_digest.json").read_text())
        concept = digest["candidates"][0]["concept"]
        (out / "knowledge_gap_report.json").write_text(
            json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": [
                {"concept": concept}
            ]})
        )
        (out / "expansion_need_queue.json").write_text(
            json.dumps({"items": [{
                "gap_id": "gap_1",
                "concept": concept,
                "priority": 0.70,
                "search_queries": [f"{concept} arxiv", f"{concept} survey"],
            }]})
        )
        (out / "extracted_concepts.json").write_text(
            json.dumps({"concepts": [{"concept": concept, "bucket": "knowledge_gap"}]})
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        run_stage_5(run_dir)
    with patch("scripts.auto_research_runner.stages.run_shards") as m:
        run_stage_5(run_dir)
        m.assert_not_called()


def test_run_stage_5_raises_when_weak_graph_missing(run_dir):
    (run_dir / "05_weak_graph" / "weak_global_graph.json").unlink()

    with patch("scripts.auto_research_runner.stages.run_shards") as m:
        with pytest.raises(RuntimeError, match="Stage 5 requires"):
            run_stage_5(run_dir)
        m.assert_not_called()


def test_run_stage_5_raises_when_weak_graph_missing_even_if_digest_exists(run_dir):
    (run_dir / "06_expansion" / "gap_candidates_digest.json").write_text(
        json.dumps({"candidates": []})
    )
    (run_dir / "05_weak_graph" / "weak_global_graph.json").unlink()

    with patch("scripts.auto_research_runner.stages.run_shards") as m:
        with pytest.raises(RuntimeError, match="Stage 5 requires"):
            run_stage_5(run_dir)
        m.assert_not_called()


def test_run_stage_5_fails_when_classifier_omits_extracted_concepts(run_dir):
    def fake_run_shards(_run_dir, specs, *, executor, force=False):
        out = _run_dir / "06_expansion"
        digest = json.loads((out / "gap_candidates_digest.json").read_text())
        concept = digest["candidates"][0]["concept"]
        (out / "knowledge_gap_report.json").write_text(
            json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": [
                {"concept": concept}
            ]})
        )
        (out / "expansion_need_queue.json").write_text(
            json.dumps({"items": [{
                "gap_id": "gap_1",
                "concept": concept,
                "priority": 0.70,
                "search_queries": [f"{concept} arxiv", f"{concept} survey"],
            }]})
        )

    with patch("scripts.auto_research_runner.stages.run_shards", side_effect=fake_run_shards):
        with pytest.raises(RuntimeError, match="extracted_concepts"):
            run_stage_5(run_dir)


def test_run_stage_17_writes_learning_suggestions_without_agent(tmp_path):
    run = tmp_path / "run"
    out = run / "06_expansion"
    out.mkdir(parents=True)
    (out / "gap_candidates_digest.json").write_text(json.dumps({
        "candidates": [
            {
                "concept": "CLIP vision encoder",
                "importance": 0.91,
                "evidence_refs": [{"arxiv_id": "2304.08485"}],
            }
        ]
    }))
    (out / "knowledge_gap_report.json").write_text(json.dumps({
        "knowledge_gaps": [{"concept": "CLIP vision encoder"}]
    }))
    (out / "expansion_need_queue.json").write_text(json.dumps({
        "items": [{
            "gap_id": "gap_clip",
            "concept": "CLIP vision encoder",
            "priority": 0.91,
            "search_queries": ["CLIP vision encoder arxiv", "CLIP survey"],
        }]
    }))

    with patch("scripts.auto_research_runner.stages.run_shards") as m:
        run_stage_17(run)
        m.assert_not_called()

    text = (run / "17_learning_suggestions" / "knowledge_to_add.md").read_text()
    assert "CLIP vision encoder" in text
    assert "2304.08485" in text


def test_run_stage_17_supports_legacy_stage_5_outputs_without_digest(tmp_path):
    run = tmp_path / "run"
    out = run / "06_expansion"
    out.mkdir(parents=True)
    (out / "knowledge_gap_report.json").write_text(json.dumps({
        "knowledge_gaps": [{"concept": "speech codec alignment"}]
    }))
    (out / "expansion_need_queue.json").write_text(json.dumps({
        "items": [{
            "gap_id": "gap_codec",
            "concept": "speech codec alignment",
            "priority": 0.82,
            "search_queries": ["speech codec alignment arxiv", "speech codec survey"],
        }]
    }))

    run_stage_17(run)

    text = (run / "17_learning_suggestions" / "knowledge_to_add.md").read_text()
    assert "speech codec alignment" in text
    assert "No digest metadata was available" in text
