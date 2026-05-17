from __future__ import annotations

import json
from typing import Any

from scripts.auto_research_runner.artifacts import verified_graph_fragment_filename
from scripts.auto_research_runner.config import DIRECT_SHARD_RULES


def _generic_agent_prompt(
    agent_toml: str,
    run_id: str,
    stage: str,
    shard_id: str,
    payload: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Read AGENTS.md first.",
            *DIRECT_SHARD_RULES,
            f"Run Stage {stage} only.",
            f"run_id={run_id}",
            f"shard_id={shard_id}",
            f"payload={json.dumps(payload, sort_keys=True)}",
            f"Follow {agent_toml} exactly.",
            "Write only the artifacts required by that agent and shard.",
            "Return the standard short success string.",
        ]
    )


def _stage_11_prompt(run_id: str, shard_id: str, arxiv_ids: list[str]) -> str:
    output_files = {
        arxiv_id: f"11_verified_graph/fragments/{verified_graph_fragment_filename(arxiv_id)}"
        for arxiv_id in arxiv_ids
    }
    return "\n".join(
        [
            "Read AGENTS.md first.",
            *DIRECT_SHARD_RULES,
            "Run Stage 11 verified graph extraction only.",
            f"run_id={run_id}",
            f"shard_id={shard_id}",
            f"arxiv_ids={arxiv_ids}",
            "Follow .codex/agents/verified_graph_extractor.toml and .agents/skills/verified-graph-extraction/SKILL.md.",
            "Read 10_verified_evidence and 05_weak_graph/fragments for these ids.",
            "Write only the 11_verified_graph/fragments/{arxiv_id}.json fragment files named below.",
            f"Use these exact output files: {output_files}",
            "Do not write 11_verified_graph/global_graph.json.",
            "Return the standard short success string.",
        ]
    )


def _typed_target_ref(target: dict[str, str]) -> str:
    singular = {"book": "book", "families": "family", "methods": "method"}[target["type"]]
    return f"{singular}:{target['id']}"
