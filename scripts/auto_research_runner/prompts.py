from __future__ import annotations

import json
from typing import Any

from scripts.auto_research_runner.artifacts import (
    verified_graph_fragment_filename,
    verified_graph_frame_relpath,
)
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


def _stage_11_prompt(
    run_id: str,
    shard_id: str,
    arxiv_ids: list[str],
    retry_feedback: str | None = None,
) -> str:
    output_files = {
        arxiv_id: f"11_verified_graph/fragments/{verified_graph_fragment_filename(arxiv_id)}"
        for arxiv_id in arxiv_ids
    }
    frame_files = {
        arxiv_id: verified_graph_frame_relpath(arxiv_id)
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
            "Read the Stage 11 frame files below. They contain allowed claims, nodes, and edge types.",
            f"Use these exact frame files: {frame_files}",
            "For each edge, output claim_id instead of generating source_node_id/source_lines.",
            "Use only claim_id values from the frame. Use only node ids from allowed_nodes unless proposed_nodes are explicitly justified by a claim_id.",
            "Python will copy exact source_node_id/source_lines from the selected claim_id after you write the fragment.",
            "Write only the 11_verified_graph/fragments/{arxiv_id}.json fragment files named below.",
            f"Use these exact output files: {output_files}",
            "Do not write 11_verified_graph/global_graph.json.",
            *(["", retry_feedback] if retry_feedback else []),
            "Return the standard short success string.",
        ]
    )


def _typed_target_ref(target: dict[str, str]) -> str:
    singular = {"book": "book", "families": "family", "methods": "method"}[target["type"]]
    return f"{singular}:{target['id']}"
