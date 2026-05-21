#!/usr/bin/env python3
"""Standalone driver: rebuild the web handbook for one research run."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from handbook_builder import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--milestone", default="M0", choices=["M0", "M1", "M2", "M3"])
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--executor", default="sdk")
    parser.add_argument("--skip-pnpm", action="store_true")
    args = parser.parse_args(argv)

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2

    pipeline.build(
        run_dir,
        milestone=args.milestone,
        max_workers=args.max_workers,
        executor=args.executor,
        run_pnpm_build=not args.skip_pnpm,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
