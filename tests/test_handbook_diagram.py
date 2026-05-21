from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_diagram_skill_exists():
    skill = REPO_ROOT / ".agents/skills/diagram-author/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "Mermaid" in text or "mermaid" in text
    assert "every node label" in text.lower() or "node labels" in text.lower()
    assert ".mmd" in text


def test_diagram_toml_exists():
    toml = REPO_ROOT / ".codex/agents/diagram_author.toml"
    assert toml.exists()
    assert 'name = "diagram_author"' in toml.read_text()


def test_validate_mermaid_node_provenance():
    from handbook_builder.diagrams import validate_node_provenance

    allowed = {"MaskGCT", "Tokenizer", "Decoder"}
    good = "graph LR; Tokenizer --> MaskGCT --> Decoder"
    validate_node_provenance(good, allowed)

    bad = "graph LR; Tokenizer --> WaveNet --> Decoder"
    import pytest
    with pytest.raises(ValueError) as ex:
        validate_node_provenance(bad, allowed)
    assert "WaveNet" in str(ex.value)


def test_build_diagram_specs(tmp_path):
    from handbook_builder.diagrams import build_diagram_specs

    run_dir = tmp_path / "run-z"
    (run_dir / "12_taxonomy").mkdir(parents=True)
    (run_dir / "13_chapter_packs/methods").mkdir(parents=True)
    (run_dir / "12_taxonomy/outline.json").write_text('{"families":[{"id":"codec-tts"},{"id":"non-ar-tts"}],"methods":[{"id":"maskgct"}]}')
    (run_dir / "13_chapter_packs/methods/maskgct.json").write_text("{}")

    specs = build_diagram_specs(run_dir)
    ids = {s.shard_id for s in specs}
    assert "diagram-family-codec-tts" in ids
    assert "diagram-method-maskgct" in ids
    assert all(s.stage == "19" for s in specs)
