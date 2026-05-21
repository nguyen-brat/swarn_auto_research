"""Invoke pnpm install + build inside a run's 19_handbook directory."""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from handbook_builder.deploy import PublishConfig
from handbook_builder.validation import validate_built_site


def run_pnpm_build(run_dir: Path, *, publish_config: PublishConfig | None = None) -> None:
    cwd = run_dir / "19_handbook"
    package_manager = "pnpm" if shutil.which("pnpm") else "npm"
    install_cmd = (
        ["pnpm", "install", "--frozen-lockfile=false"]
        if package_manager == "pnpm"
        else ["npm", "install"]
    )
    build_cmd = ["pnpm", "build"] if package_manager == "pnpm" else ["npm", "run", "build"]
    for cmd in (install_cmd, build_cmd):
        result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            _write_build_error(cwd, cmd, result.stdout, result.stderr)
            raise RuntimeError(
                f"pnpm command failed: {' '.join(cmd)}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
    validate_built_site(run_dir, publish_config=publish_config)


def _write_build_error(cwd: Path, cmd: list[str], stdout: str, stderr: str) -> None:
    (cwd / "BUILD_ERROR.txt").write_text(
        "Command failed: "
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + stdout[-4000:]
        + "\n\nSTDERR:\n"
        + stderr[-4000:]
        + "\n"
    )
