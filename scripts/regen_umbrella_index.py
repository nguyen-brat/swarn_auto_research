#!/usr/bin/env python3
"""Regenerate handbook/src/content/docs/runs/*.mdx from research_runs/*."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def regenerate(repo_root: Path) -> None:
    runs_root = repo_root / "research_runs"
    dst = repo_root / "handbook/src/content/docs/runs"
    dst.mkdir(parents=True, exist_ok=True)
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        config_path = run_dir / "run_config.json"
        if not config_path.exists():
            continue
        config = json.loads(config_path.read_text())
        run_id = config.get("run_id", run_dir.name)
        topic = config.get("topic", run_id)
        created_at = config.get("created_at", "")
        built = (run_dir / "19_handbook/dist").exists()
        status = "✓ built" if built else "pending"
        body = (
            f"---\ntitle: \"{topic}\"\ndescription: \"Run {run_id}\"\n---\n\n"
            f"**Run id:** `{run_id}`\n\n"
            f"**Created:** {created_at}\n\n"
            f"Build status: {status}\n\n"
            f"[Open run handbook](/runs/{run_id}/)\n"
        )
        (dst / f"{run_id}.mdx").write_text(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    regenerate(args.repo_root.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
