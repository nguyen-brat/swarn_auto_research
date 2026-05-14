"""Sanity checks for the .codex/agents and .agents/skills scaffold."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from swarn_research_mcp.research_book import FAMILY_REQUIRED_HEADINGS, METHOD_REQUIRED_HEADINGS

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".codex" / "agents"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

EXPECTED_AGENTS = {
    "query_planner",
    "knowledge_base_reader",
    "weak_evidence_extractor",
    "weak_graph_extractor",
    "knowledge_gap_detector",
    "paper_expander",
    "paper_ranker",
    "paper_indexer",
    "verified_evidence_extractor",
    "verified_graph_extractor",
    "outline_planner",
    "chapter_pack_builder",
    "method_chapter_writer",
    "family_chapter_writer",
    "book_section_writer",
    "verifier",
    "chapter_manifest_builder",
}

EXPECTED_SKILLS = {
    "deep-research-supervisor",
    "auto-research-orchestrator",
    "query-planning",
    "knowledge-base-reading",
    "weak-evidence-extraction",
    "weak-graph-extraction",
    "knowledge-gap-detection",
    "paper-pool-expansion",
    "pageindex-building",
    "verified-evidence-extraction",
    "verified-graph-extraction",
    "taxonomy-building",
    "chapter-pack-building",
    "method-chapter-writing",
    "family-chapter-writing",
    "book-section-writing",
    "verification",
    "chapter-manifest",
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


def test_chapter_writer_agents_match_validator_heading_contracts():
    method_prompt = tomllib.loads((AGENTS_DIR / "method_chapter_writer.toml").read_text())[
        "developer_instructions"
    ]
    family_prompt = tomllib.loads((AGENTS_DIR / "family_chapter_writer.toml").read_text())[
        "developer_instructions"
    ]
    verifier_prompt = tomllib.loads((AGENTS_DIR / "verifier.toml").read_text())[
        "developer_instructions"
    ]

    for heading in METHOD_REQUIRED_HEADINGS:
        assert heading.removeprefix("## ") in method_prompt
        assert heading in verifier_prompt
    for stale_heading in ("## Example", "## Software"):
        assert stale_heading not in method_prompt

    for heading in FAMILY_REQUIRED_HEADINGS:
        assert heading.removeprefix("## ") in family_prompt
        assert heading in verifier_prompt
    for stale_heading in (
        "What this family is",
        "Core design pattern",
        "When this family is useful",
        "Methods in this family",
        "How this family compares to others",
        "Boundary cases and overlaps",
    ):
        assert stale_heading not in family_prompt


def test_orchestrator_skill_references_all_agents():
    skill_md = (SKILLS_DIR / "auto-research-orchestrator" / "SKILL.md").read_text()
    for agent in EXPECTED_AGENTS:
        assert agent in skill_md, f"orchestrator does not mention {agent}"


def test_deep_research_supervisor_warns_bootstrap_can_be_long():
    skill_md = (SKILLS_DIR / "deep-research-supervisor" / "SKILL.md").read_text()
    assert "40+ minutes" in skill_md
    assert "Do not interrupt" in skill_md


def test_config_toml_has_mcp_server_block():
    config = tomllib.loads((REPO_ROOT / ".codex" / "config.toml").read_text())
    assert "mcp_servers" in config
    assert "swarn-auto-research" in config["mcp_servers"]
