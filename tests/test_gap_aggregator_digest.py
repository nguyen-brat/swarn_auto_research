import json
import shutil
from pathlib import Path

import pytest

from knowledge_gap_aggregator import build_digest

FIXTURE = Path(__file__).parent / "fixtures" / "weak_graph_mini"


@pytest.fixture
def run_dir(tmp_path):
    dest = tmp_path / "run"
    dest.mkdir()
    (dest / "05_weak_graph").mkdir()
    (dest / "04_weak_evidence").mkdir()
    (dest / "06_expansion").mkdir()
    shutil.copy(
        FIXTURE / "weak_global_graph.json",
        dest / "05_weak_graph" / "weak_global_graph.json",
    )
    for f in (FIXTURE / "04_weak_evidence").iterdir():
        shutil.copy(f, dest / "04_weak_evidence" / f.name)
    (dest / "06_expansion" / "known_concepts_snapshot.json").write_text(
        (FIXTURE / "known_concepts_snapshot.json").read_text()
    )
    return dest


def _load_digest(run_dir):
    return json.loads(
        (run_dir / "06_expansion" / "gap_candidates_digest.json").read_text()
    )


def test_build_digest_writes_file(run_dir):
    build_digest(run_dir, run_id="test-run")
    out = run_dir / "06_expansion" / "gap_candidates_digest.json"
    assert out.exists()
    data = _load_digest(run_dir)
    assert data["run_id"] == "test-run"
    assert "candidates" in data
    assert data["params"]["top_n"] == 100
    assert data["params"]["hard_cap"] == 120


def test_build_digest_drops_known_concepts(run_dir):
    build_digest(run_dir, run_id="test-run")
    names = [c["normalized"] for c in _load_digest(run_dir)["candidates"]]
    assert "transformer" not in names


def test_build_digest_includes_real_method(run_dir):
    build_digest(run_dir, run_id="test-run")
    names = [c["normalized"] for c in _load_digest(run_dir)["candidates"]]
    assert "vit" in names
    assert "clip vision encoder" in names


def test_build_digest_respects_hard_cap(tmp_path):
    run = tmp_path / "run"
    (run / "05_weak_graph").mkdir(parents=True)
    (run / "04_weak_evidence").mkdir()
    (run / "06_expansion").mkdir()
    methods = [f"concept_{i}" for i in range(1000)]
    (run / "05_weak_graph" / "weak_global_graph.json").write_text(
        json.dumps({"nodes": [{"id": "p1", "type": "Paper"}], "edges": []})
    )
    (run / "04_weak_evidence" / "p1.json").write_text(json.dumps({
        "arxiv_id": "p1", "title": "", "methods": methods,
        "datasets": [], "benchmarks": [], "baselines": [], "metrics": [],
        "topic_tags": [], "mentioned_entities": [], "reader_needed_concepts": [],
        "book_usage": {"importance_score_1_to_5": 5},
    }))
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text(
        json.dumps({"aliases": {}})
    )
    build_digest(run, run_id="big")
    assert len(_load_digest(run)["candidates"]) <= 120


def test_build_digest_signals_and_evidence_present(run_dir):
    build_digest(run_dir, run_id="test-run")
    c = _load_digest(run_dir)["candidates"][0]
    assert "signals" in c and "importance" in c
    assert "paper_count" in c["signals"]
    assert "is_method_of_core" in c["signals"]
    assert isinstance(c.get("evidence_refs"), list)
    assert isinstance(c.get("graph_neighbors"), list)


def test_build_digest_writes_aggregator_log(run_dir):
    build_digest(run_dir, run_id="test-run")
    log = run_dir / "06_expansion" / "aggregator_log.json"
    assert log.exists()
    data = json.loads(log.read_text())
    assert "dropped" in data


def test_build_digest_includes_graph_only_concepts(run_dir):
    """A concept present in weak_global_graph.json but in no evidence file
    must still appear as a candidate (or be in `dropped` with a real reason)."""
    build_digest(run_dir, run_id="test-run")
    names = [c["normalized"] for c in _load_digest(run_dir)["candidates"]]
    log = json.loads(
        (run_dir / "06_expansion" / "aggregator_log.json").read_text()
    )
    dropped_names = [d["concept"].lower() for d in log["dropped"]]
    assert "graph only concept" in names or "graph only concept" in dropped_names


def test_build_digest_neighbors_use_graph_not_just_evidence(run_dir):
    """If two concepts share a paper in the GRAPH but never co-occur in
    evidence fields, the graph co-occurrence still surfaces them as neighbors."""
    build_digest(run_dir, run_id="test-run")
    data = _load_digest(run_dir)
    by_norm = {c["normalized"]: c for c in data["candidates"]}
    if "vit" in by_norm:
        assert any("graph only" in n.lower() for n in by_norm["vit"]["graph_neighbors"]) \
            or any("clip" in n.lower() for n in by_norm["vit"]["graph_neighbors"])


def test_build_digest_enforces_size_budget(tmp_path):
    """Synthetic high-text fixture: snippets and names are long enough that
    naive serialization would blow past 100 KB. The aggregator must cap."""
    run = tmp_path / "run"
    (run / "05_weak_graph").mkdir(parents=True)
    (run / "04_weak_evidence").mkdir()
    (run / "06_expansion").mkdir()

    long_word = "x" * 500
    methods = [f"{long_word}_{i}" for i in range(300)]
    long_text = ["aaaa " * 200] * 5
    (run / "05_weak_graph" / "weak_global_graph.json").write_text(
        json.dumps({"nodes": [{"id": "p1", "type": "Paper"}], "edges": []})
    )
    (run / "04_weak_evidence" / "p1.json").write_text(json.dumps({
        "arxiv_id": "p1", "title": "", "methods": methods,
        "datasets": [], "benchmarks": [], "baselines": [], "metrics": [],
        "topic_tags": [], "mentioned_entities": [], "reader_needed_concepts": [],
        "problem": long_text, "solution": long_text,
        "book_usage": {"importance_score_1_to_5": 5},
    }))
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text(
        json.dumps({"aliases": {}})
    )
    build_digest(run, run_id="big")
    out = run / "06_expansion" / "gap_candidates_digest.json"
    size = out.stat().st_size
    assert size <= 100_000, f"digest file is {size} bytes — exceeds 100 KB budget"
