"""Diagram sub-stage: spec builder + post-hoc validation."""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.auto_research_runner.prompts import _generic_agent_prompt
from scripts.auto_research_runner.shared_types import ShardSpec


NODE_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_\- ]*)\b")


def build_diagram_specs(run_dir: Path) -> list[ShardSpec]:
    outline = json.loads((run_dir / "12_taxonomy/outline.json").read_text())
    specs: list[ShardSpec] = []

    for family in outline.get("families", []):
        fid = family["id"]
        if fid == "standalone" or family.get("is_group"):
            continue
        specs.append(_make_spec(run_dir, "family", fid, "12_taxonomy/outline.json"))

    for method in outline.get("methods", []):
        mid = method["id"]
        specs.append(
            _make_spec(run_dir, "method", mid, f"13_chapter_packs/methods/{mid}.json")
        )

    return specs


def _make_spec(run_dir: Path, target_type: str, target_id: str, source_path: str) -> ShardSpec:
    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "source_path": source_path,
    }
    plural = "families" if target_type == "family" else "methods"
    return ShardSpec(
        stage="19",
        shard_id=f"diagram-{target_type}-{target_id}",
        agent="diagram_author",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/diagram_author.toml",
            run_dir.name,
            "19",
            f"diagram-{target_type}-{target_id}",
            payload,
        ),
        expected_outputs=[
            f"19_handbook/src/assets/diagrams/{plural}/{target_id}.mmd"
        ],
    )


def validate_node_provenance(mermaid_source: str, allowed_names: set[str]) -> None:
    """Reject diagrams whose node labels are absent from the source JSON."""
    body = re.sub(r"^\s*graph\s+\w+;?", "", mermaid_source, count=1).strip()
    tokens = set()
    for line in body.splitlines():
        line = line.split("%%")[0]  # strip mermaid comments
        for match in re.findall(r"([A-Z][A-Za-z0-9_\-]*)\b", line):
            tokens.add(match)
    skipped = {"TD", "LR", "TB", "BT", "RL"}
    unknown = (tokens - allowed_names) - skipped
    if unknown:
        raise ValueError(f"diagram references unknown nodes: {sorted(unknown)}")
