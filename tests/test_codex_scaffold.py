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


def test_family_writer_contract_forbids_out_of_pack_names():
    skill_md = (SKILLS_DIR / "family-chapter-writing" / "SKILL.md").read_text()
    agent_prompt = tomllib.loads((AGENTS_DIR / "family_chapter_writer.toml").read_text())[
        "developer_instructions"
    ]

    for source in (skill_md, agent_prompt):
        normalized = re.sub(r"\s+", " ", source.replace("`", "")).lower()
        assert "do not name any method, paper, library, system, model, benchmark, or dataset" in normalized
        assert "not present in the pack scope" in normalized
        assert "pack.method_ids" in normalized
        assert "pack.comparison_rows" in normalized
        assert "pack.neighbor_family_ids" in normalized
        assert "if a famous method is relevant" in normalized
        assert "not in the pack" in normalized
        assert "omit it" in normalized
        assert "main variants" in normalized
        assert "table rows" in normalized
        assert "equal pack.method_ids exactly" in normalized
        assert "≥ 1 row per method" not in source


def test_verifier_contract_allows_family_and_book_synthesis():
    skill_md = (SKILLS_DIR / "verification" / "SKILL.md").read_text()
    agent_prompt = tomllib.loads((AGENTS_DIR / "verifier.toml").read_text())[
        "developer_instructions"
    ]

    for source in (skill_md, agent_prompt):
        normalized = re.sub(r"\s+", " ", source.replace("`", "")).lower()
        assert "synthesis claims for family and book chapters" in normalized
        assert "do not downgrade" in normalized
        assert "synthesizes across" in normalized
        assert "all named methods are present in the pack" in normalized
        assert "book:*" in normalized
        assert "pack or outline" in normalized
        assert "partially_supported is informational" in normalized
        assert "not counted as claims_unsupported" in normalized


def test_verifier_contract_uses_pack_scoped_gap_list():
    skill_md = (SKILLS_DIR / "verification" / "SKILL.md").read_text()
    agent_prompt = tomllib.loads((AGENTS_DIR / "verifier.toml").read_text())[
        "developer_instructions"
    ]

    for source in (skill_md, agent_prompt):
        normalized = re.sub(r"\s+", " ", source.replace("`", "")).lower()
        assert "pack.knowledge_gaps_to_explain" in normalized
        assert "do not load the global knowledge_gap_report" in normalized
        assert "per-chapter required checklist" in normalized
        assert "at most 3 method gaps are required" in normalized
        assert "empty" in normalized
        assert "gaps_missing = 0" in normalized or "gaps_missing=0" in normalized
        assert '"passed"' in source


def test_chapter_pack_contract_caps_method_gap_scope():
    skill_md = (SKILLS_DIR / "chapter-pack-building" / "SKILL.md").read_text()
    agent_prompt = tomllib.loads((AGENTS_DIR / "chapter_pack_builder.toml").read_text())[
        "developer_instructions"
    ]

    for source in (skill_md, agent_prompt):
        normalized = re.sub(r"\s+", " ", source.replace("`", "")).lower()
        assert (
            "method packs must scope knowledge_gaps_to_explain to concepts actually touched by that method"
            in normalized
        )
        assert "prefer outline.methods[*].knowledge_gaps_to_explain when present" in normalized
        assert "intersect knowledge_gap_report concepts with the method" in normalized
        assert "evidence" in normalized
        assert "cap method knowledge_gaps_to_explain at 3 concepts" in normalized
        assert "do not copy the global knowledge_gap_report into every method pack" in normalized


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
