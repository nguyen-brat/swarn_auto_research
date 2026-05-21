"""Glossary sub-stage: invoke glossary-builder and validate output."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.prompts import _generic_agent_prompt
from scripts.auto_research_runner.shared_types import ShardSpec


REQUIRED_FIELDS = {"term", "definition", "appears_in", "kb_known"}


def build_glossary_spec(run_dir: Path) -> ShardSpec:
    payload = {
        "pack_dir": "13_chapter_packs/methods",
        "kb_path": ".agents/knowledge_base.md",
    }
    return ShardSpec(
        stage="19",
        shard_id="glossary-001",
        agent="glossary_builder",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/glossary_builder.toml",
            run_dir.name,
            "19",
            "glossary-001",
            payload,
        ),
        expected_outputs=["19_handbook/public/glossary.json"],
    )


def validate_glossary(entries: list[dict[str, Any]]) -> None:
    for i, entry in enumerate(entries):
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            raise ValueError(f"glossary entry {i} missing fields: {sorted(missing)}")
        if not isinstance(entry["appears_in"], list):
            raise ValueError(f"glossary entry {i} 'appears_in' must be a list")
        if not isinstance(entry["kb_known"], bool):
            raise ValueError(f"glossary entry {i} 'kb_known' must be bool")
        if len(entry["definition"]) > 280:
            raise ValueError(f"glossary entry {i} definition exceeds 280 chars")
