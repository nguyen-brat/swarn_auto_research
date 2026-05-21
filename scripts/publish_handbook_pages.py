#!/usr/bin/env python3
"""Publish a generated Stage 19 handbook dist/ directory to a Pages repo."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from handbook_builder.deploy import normalize_base_path, resolve_publish_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-id")
    source.add_argument("--run-dir", type=Path)
    source.add_argument("--dist", type=Path)
    parser.add_argument("--dest", type=Path, help="Existing local checkout of the Pages repo.")
    parser.add_argument("--repo", help="Git URL to clone when --dest is omitted.")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--base-path")
    parser.add_argument("--message", default="Publish research handbook")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print actions without writing.")
    parser.add_argument("--push", action="store_true", help="Copy, commit, and push. Without this, the script is dry-run only.")
    args = parser.parse_args(argv)

    dist = _resolve_dist(args).resolve()
    config = resolve_publish_config()
    base_path = normalize_base_path(args.base_path if args.base_path is not None else config.base_path)
    _validate_dist(dist, base_path=base_path)

    dest = _resolve_dest(args).resolve()
    _validate_dest(dest)
    _refuse_overlap(dist, dest)

    if args.dry_run or not args.push:
        print(f"dry run: would publish {dist} to {dest} on branch {args.branch}")
        return 0

    _copy_dist(dist, dest)
    _run(["git", "add", "-A"], cwd=dest)
    status = _run(["git", "status", "--porcelain"], cwd=dest).stdout.strip()
    if not status:
        print("No handbook changes to publish.")
        return 0
    _run(["git", "commit", "-m", args.message], cwd=dest)
    _run(["git", "push", "origin", args.branch], cwd=dest)
    print(f"published {dist} to {dest}")
    return 0


def _resolve_dist(args: argparse.Namespace) -> Path:
    if args.dist:
        return args.dist
    if args.run_dir:
        return args.run_dir / "19_handbook" / "dist"
    return REPO_ROOT / "research_runs" / args.run_id / "19_handbook" / "dist"


def _resolve_dest(args: argparse.Namespace) -> Path:
    if args.dest:
        return args.dest
    if not args.repo:
        raise SystemExit("--dest or --repo is required")
    name = args.repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    dest = Path(tempfile.gettempdir()) / f"handbook-pages-{name}"
    if dest.exists():
        _run(["git", "fetch", "origin", args.branch], cwd=dest)
        _run(["git", "checkout", args.branch], cwd=dest)
        _run(["git", "reset", "--hard", f"origin/{args.branch}"], cwd=dest)
    else:
        _run(["git", "clone", "--branch", args.branch, args.repo, str(dest)])
    return dest


def _validate_dist(dist: Path, *, base_path: str) -> None:
    if not dist.exists():
        raise SystemExit(f"dist not found: {dist}")
    if not (dist / ".nojekyll").exists():
        raise SystemExit(f"dist is missing .nojekyll: {dist / '.nojekyll'}")
    index = dist / "index.html"
    if not index.exists():
        raise SystemExit(f"dist is missing index.html: {index}")
    if base_path:
        text = index.read_text(errors="ignore")
        if 'href="/_astro/' in text or 'src="/_astro/' in text:
            raise SystemExit("dist contains root _astro asset references; rebuild with HANDBOOK_BASE_PATH")
        if f"{base_path}/_astro/" not in text and f'href="{base_path}/' not in text:
            raise SystemExit(f"dist index.html does not reference base path {base_path}")


def _validate_dest(dest: Path) -> None:
    if not dest.exists():
        raise SystemExit(f"destination checkout not found: {dest}")
    if not (dest / ".git").exists():
        raise SystemExit(f"destination is not a git checkout: {dest}")


def _refuse_overlap(dist: Path, dest: Path) -> None:
    if _is_relative_to(dist, dest) or _is_relative_to(dest, dist):
        raise SystemExit("source dist and destination checkout must not overlap")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _copy_dist(dist: Path, dest: Path) -> None:
    for item in dest.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in dist.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"command failed: {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
