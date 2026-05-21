from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Hashable
from contextlib import suppress
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
    completed_by_artifact: bool = False


def _attach_sdk_meta(error: BaseException, *, thread_id: str, turn_id: str) -> None:
    try:
        setattr(error, "sdk_meta", {"thread_id": thread_id, "turn_id": turn_id})
    except Exception:
        pass


async def _wait_for_stable_artifact_signature(
    artifact_signature: Callable[[], Hashable | None],
    *,
    settle_seconds: float,
) -> Hashable:
    if settle_seconds < 0:
        raise ValueError("artifact_settle_seconds must be >= 0")
    last_signature: Hashable | None = None
    stable_since: float | None = None
    poll_seconds = min(1.0, max(0.01, settle_seconds / 2 if settle_seconds else 0.01))

    while True:
        signature = await asyncio.to_thread(artifact_signature)
        now = asyncio.get_running_loop().time()
        if signature is None:
            last_signature = None
            stable_since = None
        elif signature == last_signature:
            if stable_since is None:
                stable_since = now
            if now - stable_since >= settle_seconds:
                return signature
        else:
            last_signature = signature
            stable_since = now
        await asyncio.sleep(poll_seconds)


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
    artifact_signature: Callable[[], Hashable | None] | None = None,
    artifact_settle_seconds: float = 10.0,
    artifact_interrupt_timeout: float = 5.0,
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
        collect_task = None
        artifact_task = None
        try:
            collect_task = asyncio.create_task(
                _collect_async_run_result(stream, turn_id=turn.id)
            )
            if artifact_signature is None:
                result = await asyncio.wait_for(collect_task, timeout=timeout)
            else:
                artifact_task = asyncio.create_task(
                    _wait_for_stable_artifact_signature(
                        artifact_signature,
                        settle_seconds=artifact_settle_seconds,
                    )
                )
                done, _pending = await asyncio.wait(
                    {collect_task, artifact_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise TimeoutError(f"Timed out waiting for turn {turn.id}")
                if collect_task in done:
                    result = collect_task.result()
                    artifact_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await artifact_task
                else:
                    artifact_task.result()
                    with suppress(Exception, asyncio.TimeoutError):
                        await asyncio.wait_for(
                            turn.interrupt(),
                            timeout=artifact_interrupt_timeout,
                        )
                    collect_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await collect_task
                    return OneShotResult(
                        thread_id=thread.id,
                        turn_id=turn.id,
                        final_response="accepted after expected outputs became stable",
                        usage=None,
                        completed_by_artifact=True,
                    )
        except BaseException as error:
            _attach_sdk_meta(error, thread_id=thread.id, turn_id=turn.id)
            raise
        finally:
            for task in (collect_task, artifact_task):
                if task is not None and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await task
            if hasattr(stream, "aclose"):
                await stream.aclose()
        return OneShotResult(
            thread_id=thread.id,
            turn_id=turn.id,
            final_response=result.final_response or "",
            usage=result.usage,
            completed_by_artifact=False,
        )


def run_one_shot_sync(
    *,
    prompt: str,
    model: str,
    cwd: Path | str | None = None,
    timeout: float = 3600.0,
    notification_timeout: float | None = None,
    artifact_signature: Callable[[], Hashable | None] | None = None,
    artifact_settle_seconds: float = 10.0,
    artifact_interrupt_timeout: float = 5.0,
) -> OneShotResult:
    return asyncio.run(
        run_one_shot(
            prompt=prompt,
            model=model,
            cwd=cwd,
            timeout=timeout,
            notification_timeout=notification_timeout,
            artifact_signature=artifact_signature,
            artifact_settle_seconds=artifact_settle_seconds,
            artifact_interrupt_timeout=artifact_interrupt_timeout,
        )
    )


async def main() -> None:
    async with AsyncCodex(config=build_config()) as codex:
        thread = await codex.thread_start(model="gpt-5.4")
        result = await thread.run("Hello")
        print(result.final_response)


if __name__ == "__main__":
    asyncio.run(main())
