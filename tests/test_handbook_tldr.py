import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tldr_skill_exists():
    skill = REPO_ROOT / ".agents/skills/web-tldr-writer/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "MUST be grounded" in text or "must appear in" in text.lower()
    assert "tldr" in text
    assert "key_idea" in text
    assert "when_to_use" in text
    assert "tags" in text
    assert "tags_vocab.json" in text
    assert "280" in text
    assert "140" in text


def test_tldr_toml_exists():
    toml = REPO_ROOT / ".codex/agents/web_tldr_writer.toml"
    assert toml.exists()
    assert 'name = "web_tldr_writer"' in toml.read_text()


def test_tags_vocab_present():
    vocab = REPO_ROOT / "handbook_builder/tags_vocab.json"
    assert vocab.exists()
    data = json.loads(vocab.read_text())
    assert isinstance(data, list)
    assert len(data) >= 10
    for tag in data:
        assert isinstance(tag, str)
