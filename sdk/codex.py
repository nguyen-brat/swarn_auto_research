from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import NamedTuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = Path(__file__).resolve().parent
SDK_PACKAGE_ROOT = SDK_ROOT / "codex_app_server"

if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

import asyncio

from codex_app_server import AppServerConfig, AsyncCodex, TextInput
from codex_app_server._run import _collect_async_run_result


class OneShotResult(NamedTuple):
    thread_id: str
    turn_id: str
    final_response: str
    usage: object | None = None


def resolve_codex_bin() -> str:
    explicit = os.environ.get("CODEX_BIN")
    if explicit:
        codex_bin = Path(explicit).expanduser()
        if not codex_bin.exists():
            raise FileNotFoundError(f"CODEX_BIN points to a missing file: {codex_bin}")
        return str(codex_bin)

    codex_on_path = shutil.which("codex")
    if codex_on_path is not None:
        return codex_on_path

    raise RuntimeError(
        "Could not find a `codex` binary. Install the Codex CLI, add it to PATH, "
        "or set CODEX_BIN to the binary location."
    )


def build_config(cwd: Path | str | None = None) -> AppServerConfig:
    return AppServerConfig(
        codex_bin=resolve_codex_bin(),
        cwd=str(cwd or REPO_ROOT),
    )


async def run_one_shot(
    *,
    prompt: str,
    model: str,
    cwd: Path | str | None = None,
    timeout: float = 3600.0,
    notification_timeout: float | None = None,
) -> OneShotResult:
    async with AsyncCodex(config=build_config(cwd)) as codex:
        thread = await codex.thread_start(
            model=model,
            cwd=str(cwd or REPO_ROOT),
            approval_policy="never",
            sandbox="workspace-write",
        )
        turn = await thread.turn(
            TextInput(prompt),
            cwd=str(cwd or REPO_ROOT),
            approval_policy="never",
        )
        stream = turn.stream(
            notification_timeout_s=(
                timeout if notification_timeout is None else notification_timeout
            )
        )
        try:
            result = await asyncio.wait_for(
                _collect_async_run_result(stream, turn_id=turn.id),
                timeout=timeout,
            )
        finally:
            if hasattr(stream, "aclose"):
                await stream.aclose()
        return OneShotResult(
            thread_id=thread.id,
            turn_id=turn.id,
            final_response=result.final_response or "",
            usage=result.usage,
        )


def run_one_shot_sync(
    *,
    prompt: str,
    model: str,
    cwd: Path | str | None = None,
    timeout: float = 3600.0,
    notification_timeout: float | None = None,
) -> OneShotResult:
    return asyncio.run(
        run_one_shot(
            prompt=prompt,
            model=model,
            cwd=cwd,
            timeout=timeout,
            notification_timeout=notification_timeout,
        )
    )


async def main() -> None:
    async with AsyncCodex(config=build_config()) as codex:
        thread = await codex.thread_start(model="gpt-5.4")
        result = await thread.run("Hello")
        print(result.final_response)


if __name__ == "__main__":
    asyncio.run(main())
