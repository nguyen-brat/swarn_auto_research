from __future__ import annotations

import os
import signal
from pathlib import Path
from time import sleep
from typing import Any

from scripts.auto_research_runner.config import REPO_ROOT
from scripts.auto_research_runner.io_utils import _path_is_relative_to
from scripts.auto_research_runner.state import append_run_log


def _read_proc_cmdline(proc_dir: Path) -> list[str]:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _proc_cwd_is_under_repo(proc_dir: Path, repo_root: Path) -> bool:
    try:
        cwd = (proc_dir / "cwd").resolve()
    except OSError:
        return False
    return cwd == repo_root or _path_is_relative_to(cwd, repo_root)


def _find_research_mcp_pids(
    *,
    proc_root: Path = Path("/proc"),
    repo_root: Path = REPO_ROOT,
    current_pid: int | None = None,
) -> list[int]:
    repo_root = repo_root.resolve()
    current_pid = os.getpid() if current_pid is None else current_pid
    pids: list[int] = []
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:
            continue
        cmdline = _read_proc_cmdline(proc_dir)
        joined = " ".join(cmdline)
        if "swarn-auto-research-mcp" not in joined:
            continue
        if _proc_cwd_is_under_repo(proc_dir, repo_root) or str(repo_root) in joined:
            pids.append(pid)
    return sorted(pids)


def cleanup_orphaned_research_mcp_processes(
    *,
    proc_root: Path = Path("/proc"),
    repo_root: Path = REPO_ROOT,
    grace_seconds: float = 2.0,
    kill_func: Any = os.kill,
) -> list[int]:
    pids = _find_research_mcp_pids(proc_root=proc_root, repo_root=repo_root)
    for pid in pids:
        try:
            kill_func(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if pids and grace_seconds > 0:
        sleep(grace_seconds)
    for pid in pids:
        if not (proc_root / str(pid)).exists():
            continue
        try:
            kill_func(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return pids


def cleanup_stage_6_research_mcp_processes(run_dir: Path) -> None:
    try:
        cleaned = cleanup_orphaned_research_mcp_processes()
    except Exception as error:
        append_run_log(run_dir, "6", "cleanup_failed", f"{type(error).__name__}: {error}")
        return
    if cleaned:
        append_run_log(
            run_dir,
            "6",
            "cleanup",
            f"terminated orphaned research MCP processes: {cleaned}",
        )
