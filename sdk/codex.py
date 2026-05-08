from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = Path(__file__).resolve().parent
SDK_PACKAGE_ROOT = SDK_ROOT / "codex_app_server"

if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

import asyncio

from codex_app_server import AppServerConfig, AsyncCodex


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


def build_config() -> AppServerConfig:
    return AppServerConfig(
        codex_bin=resolve_codex_bin(),
        cwd=str(REPO_ROOT),
    )


async def main() -> None:
    async with AsyncCodex(config=build_config()) as codex:
        thread = await codex.thread_start(model="gpt-5.4")
        result = await thread.run("Hello")
        print(result.final_response)


if __name__ == "__main__":
    asyncio.run(main())
