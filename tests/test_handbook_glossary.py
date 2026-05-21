from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_glossary_skill_exists():
    skill = REPO_ROOT / ".agents/skills/glossary-builder/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "knowledge_base.md" in text
    assert "kb_known" in text
    assert "appears_in" in text
    assert "definition" in text


def test_glossary_toml_exists():
    toml = REPO_ROOT / ".codex/agents/glossary_builder.toml"
    assert toml.exists()
    assert 'name = "glossary_builder"' in toml.read_text()


def test_validate_glossary_schema(tmp_path):
    from handbook_builder.glossary import validate_glossary

    good = [
        {"term": "RVQ", "definition": "Residual VQ.", "appears_in": ["maskgct"], "kb_known": False},
        {"term": "Z", "definition": "Z.", "appears_in": [], "kb_known": True},
    ]
    validate_glossary(good)  # should not raise

    bad = [{"term": "X"}]
    import pytest
    with pytest.raises(ValueError):
        validate_glossary(bad)


def test_build_glossary_spec(tmp_path):
    from handbook_builder.glossary import build_glossary_spec

    run_dir = tmp_path / "run-y"
    run_dir.mkdir()
    spec = build_glossary_spec(run_dir)
    assert spec.stage == "19"
    assert spec.shard_id == "glossary-001"
    assert spec.agent == "glossary_builder"
    assert spec.expected_outputs == ["19_handbook/public/glossary.json"]
