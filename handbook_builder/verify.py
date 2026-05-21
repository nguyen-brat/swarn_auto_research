"""Adapter for the verification-web agent."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts.auto_research_runner.prompts import _generic_agent_prompt
from scripts.auto_research_runner.shared_types import ShardSpec

Kind = Literal["tldr", "book_rewrite"]


@dataclass
class VerificationResult:
    passed: bool
    rejection_reason: str | None
    claims: list[dict[str, Any]]


def build_verifier_spec(
    run_dir: Path,
    *,
    kind: Kind,
    target_id: str,
    original_path: str,
    candidate_path: str,
) -> ShardSpec:
    expected = f"19_handbook/.augment/{kind}/{target_id}.verification.json"
    payload = {
        "kind": kind,
        "original_path": original_path,
        "candidate_path": candidate_path,
    }
    return ShardSpec(
        stage="19",
        shard_id=f"verify-{kind}-{target_id}",
        agent="verifier_web",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/verifier_web.toml",
            run_dir.name,
            "19",
            f"verify-{kind}-{target_id}",
            payload,
        ),
        expected_outputs=[expected],
    )


def load_verification_result(path: Path) -> VerificationResult:
    data = json.loads(path.read_text())
    return VerificationResult(
        passed=bool(data.get("passed", False)),
        rejection_reason=data.get("rejection_reason"),
        claims=list(data.get("claims", [])),
    )
