"""Adapter around the refactored auto-research shard runner for Stage 19."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.prompts import _generic_agent_prompt
from scripts.auto_research_runner.shards import run_shards
from scripts.auto_research_runner.shared_types import ShardSpec


def build_curator_spec(
    run_dir: Path,
    *,
    topic: str,
    manifest: list[dict[str, Any]],
    parts: list[dict[str, Any]],
) -> ShardSpec:
    payload = {"topic": topic, "chapter_manifest": manifest, "parts": parts}
    return ShardSpec(
        stage="19",
        shard_id="scaffold-001",
        agent="web_design_curator",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/web_design_curator.toml",
            run_dir.name,
            "19",
            "scaffold-001",
            payload,
        ),
        expected_outputs=["19_handbook/.scaffold/curator_output.json"],
    )


def run_handbook_shards(
    run_dir: Path,
    specs: list[ShardSpec],
    *,
    max_workers: int = 1,
    executor: str = "sdk",
) -> None:
    if not specs:
        return
    run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
