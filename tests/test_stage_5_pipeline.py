import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_auto_research import run_stage_5

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

    def fake_run_shards(_run_dir, specs, *, executor):
        captured.extend(specs)
        out = _run_dir / "06_expansion"
        (out / "knowledge_gap_report.json").write_text(
            json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": []})
        )
        (out / "expansion_need_queue.json").write_text(
            json.dumps({"items": []})
        )
        (out / "extracted_concepts.json").write_text(json.dumps([]))

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_5(run_dir)

    assert (run_dir / "06_expansion" / "gap_candidates_digest.json").exists()
    assert len(captured) == 1
    assert captured[0].agent == "knowledge_gap_classifier"


def test_run_stage_5_idempotent_when_report_present(run_dir):
    (run_dir / "06_expansion" / "knowledge_gap_report.json").write_text(
        json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": []})
    )
    with patch("scripts.run_auto_research.run_shards") as m:
        run_stage_5(run_dir)
        m.assert_not_called()
