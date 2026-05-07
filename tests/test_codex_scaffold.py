"""Sanity checks for the .codex/agents and .agents/skills scaffold."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".codex" / "agents"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

EXPECTED_AGENTS = {
    "knowledge_base_reader",
    "weak_evidence_extractor",
    "weak_graph_extractor",
    "knowledge_gap_detector",
    "paper_expander",
    "paper_ranker",
    "paper_indexer",
    "chapter_writer",
    "verifier",
}

EXPECTED_SKILLS = {
    "auto-research-orchestrator",
    "knowledge-base-reading",
    "weak-evidence-extraction",
    "weak-graph-extraction",
    "knowledge-gap-detection",
    "paper-pool-expansion",
    "pageindex-building",
    "chapter-writing",
    "verification",
}


def test_all_agents_present():
    found = {p.stem for p in AGENTS_DIR.glob("*.toml")}
    assert found == EXPECTED_AGENTS


def test_all_skills_present():
    found = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}
    assert found == EXPECTED_SKILLS
    for skill_name in EXPECTED_SKILLS:
        assert (SKILLS_DIR / skill_name / "SKILL.md").is_file(), skill_name


def test_agents_parse_and_have_required_keys():
    for toml_path in AGENTS_DIR.glob("*.toml"):
        data = tomllib.loads(toml_path.read_text())
        for key in ("name", "description", "model", "developer_instructions"):
            assert key in data, f"{toml_path.name} missing {key}"
        assert data["name"] == toml_path.stem


def test_agents_only_use_codex_known_fields():
    """Codex rejects unknown fields (deny_unknown_fields)."""
    allowed = {
        "name",
        "description",
        "nickname_candidates",
        "developer_instructions",
        "model",
        "model_reasoning_effort",
        "sandbox_mode",
        "mcp_servers",
        "skills",
    }
    for toml_path in AGENTS_DIR.glob("*.toml"):
        data = tomllib.loads(toml_path.read_text())
        unknown = set(data) - allowed
        assert not unknown, f"{toml_path.name} has unknown fields: {unknown}"


def test_agent_skill_references_resolve():
    """Every SKILL.md path mentioned in an agent prompt must exist."""
    pattern = re.compile(r"\.agents/skills/([a-z\-]+)/SKILL\.md")
    for toml_path in AGENTS_DIR.glob("*.toml"):
        data = tomllib.loads(toml_path.read_text())
        for skill_name in pattern.findall(data["developer_instructions"]):
            assert (SKILLS_DIR / skill_name / "SKILL.md").is_file(), (
                f"{toml_path.name} references missing skill {skill_name}"
            )


def test_orchestrator_skill_references_all_agents():
    skill_md = (SKILLS_DIR / "auto-research-orchestrator" / "SKILL.md").read_text()
    for agent in EXPECTED_AGENTS:
        assert agent in skill_md, f"orchestrator does not mention {agent}"


def test_config_toml_has_mcp_server_block():
    config = tomllib.loads((REPO_ROOT / ".codex" / "config.toml").read_text())
    assert "mcp_servers" in config
    assert "swarn-auto-research" in config["mcp_servers"]
