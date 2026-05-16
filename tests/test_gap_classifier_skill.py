from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[1]
    / ".agents" / "skills" / "knowledge-gap-classification" / "SKILL.md"
)


def test_skill_exists():
    assert SKILL.exists()


def test_skill_contains_load_bearing_rules():
    text = SKILL.read_text()
    lower = text.lower()
    assert "do not re-derive importance" in lower
    assert "must appear in" in lower
    assert "0.70" in text
    assert "gap_candidates_digest.json" in text


def test_skill_forbids_reading_raw_inputs():
    text = SKILL.read_text()
    assert "05_weak_graph/weak_global_graph.json" in text
    assert "04_weak_evidence/" in text
    assert "DO NOT" in text or "do not read" in text.lower()
