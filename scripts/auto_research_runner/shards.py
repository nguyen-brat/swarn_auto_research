from __future__ import annotations

import json
import os
import re
import subprocess
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import (
    DEFAULT_EXECUTOR,
    DEFAULT_MAX_EFFECTIVE_WORKERS,
    DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS,
    DEFAULT_SHARD_TIMEOUT_SECONDS,
    DEFAULT_STAGE_MAX_EFFECTIVE_WORKERS,
    REPO_ROOT,
)
from scripts.auto_research_runner.io_utils import _safe_relative_path, _safe_component
from scripts.auto_research_runner.shared_types import ShardAttemptResult, ShardSpec
from scripts.auto_research_runner.state import (
    append_run_log,
    ensure_run_control,
    now_iso,
    save_run_state,
    load_run_state,
)
from scripts.auto_research_runner.structured_json import load_structured_json_file


def _validate_shard_spec(spec: ShardSpec) -> None:
    _safe_component(spec.stage, field="stage")
    _safe_component(spec.shard_id, field="shard_id")
    for rel in spec.expected_outputs:
        _safe_relative_path(rel, field="expected output")


def _expected_output_exists(run_dir: Path, spec: ShardSpec, rel_path: str) -> bool:
    path = run_dir / _safe_relative_path(rel_path, field="expected output")
    if not path.exists():
        return False
    if spec.stage == "10" and rel_path.startswith("10_verified_evidence/") and rel_path.endswith(".json"):
        try:
            evidence = load_structured_json_file(path, canonicalize=True)
        except (OSError, json.JSONDecodeError):
            return False
        claims = evidence.get("claims") if isinstance(evidence, dict) else None
        return isinstance(claims, list)
    return True


def expected_outputs_exist(run_dir: Path, spec: ShardSpec) -> bool:
    _validate_shard_spec(spec)
    return all(_expected_output_exists(run_dir, spec, rel) for rel in spec.expected_outputs)


def _shard_dir(run_dir: Path, spec: ShardSpec) -> Path:
    _validate_shard_spec(spec)
    path = ensure_run_control(run_dir) / "stages" / spec.stage / "shards"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_shard_manifest(
    run_dir: Path,
    spec: ShardSpec,
    *,
    attempt: int,
    status: str,
    result: ShardAttemptResult,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    path = _shard_dir(run_dir, spec) / f"{spec.shard_id}.json"
    payload = {
        "stage": spec.stage,
        "shard_id": spec.shard_id,
        "agent": spec.agent,
        "model": spec.model,
        "executor": result.executor,
        "attempt": attempt,
        "expected_outputs": spec.expected_outputs,
        "status": status,
        "returncode": result.returncode,
        "thread_id": result.thread_id,
        "turn_id": result.turn_id,
        "stdout_path": str(stdout_path.relative_to(run_dir)),
        "stderr_path": str(stderr_path.relative_to(run_dir)),
        "updated_at": now_iso(),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def _append_sdk_thread_index(
    run_dir: Path,
    spec: ShardSpec,
    *,
    attempt: int,
    status: str,
    result: ShardAttemptResult,
) -> None:
    if result.executor != "sdk" or not result.thread_id:
        return
    path = ensure_run_control(run_dir) / "stages" / spec.stage / "sdk_threads.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": spec.stage,
        "shard_id": spec.shard_id,
        "attempt": attempt,
        "status": status,
        "thread_id": result.thread_id,
        "turn_id": result.turn_id,
        "updated_at": now_iso(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _next_shard_attempt(run_dir: Path, spec: ShardSpec) -> int:
    shard_dir = _shard_dir(run_dir, spec)
    prefix = f"{spec.shard_id}.attempt-"
    attempts = []
    for path in shard_dir.glob(f"{prefix}*.stderr.txt"):
        suffix = path.name.removeprefix(prefix).removesuffix(".stderr.txt")
        if suffix.isdigit():
            attempts.append(int(suffix))
    return max(attempts, default=0) + 1


def _codex_exec_command(spec: ShardSpec) -> list[str]:
    return [
        "codex",
        "exec",
        "--cd",
        str(REPO_ROOT),
        "--model",
        spec.model,
        "-c",
        'approval_policy="never"',
        "--sandbox",
        "workspace-write",
        spec.prompt,
    ]


def _run_cli_shard_attempt(
    spec: ShardSpec,
    timeout_seconds: int,
) -> ShardAttemptResult:
    completed = subprocess.run(
        _codex_exec_command(spec),
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )
    return ShardAttemptResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        executor="cli",
    )


def _sdk_notification_timeout_seconds(timeout_seconds: int) -> float:
    configured = os.environ.get("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS")
    if configured is None:
        return min(float(DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS), float(timeout_seconds))
    return min(float(configured), float(timeout_seconds))


def _run_sdk_prompt(
    prompt: str,
    *,
    model: str,
    timeout_seconds: int,
):
    from sdk.codex import run_one_shot_sync

    return run_one_shot_sync(
        prompt=prompt,
        model=model,
        cwd=REPO_ROOT,
        timeout=float(timeout_seconds),
        notification_timeout=_sdk_notification_timeout_seconds(timeout_seconds),
    )


def _run_sdk_shard_attempt(
    run_dir: Path,
    spec: ShardSpec,
    timeout_seconds: int,
) -> ShardAttemptResult:
    result = _run_sdk_prompt(
        spec.prompt,
        model=spec.model,
        timeout_seconds=timeout_seconds,
    )
    return ShardAttemptResult(
        returncode=0,
        stdout=result.final_response,
        stderr="",
        executor="sdk",
        thread_id=result.thread_id,
        turn_id=result.turn_id,
    )


def _run_shard_attempt(
    run_dir: Path,
    spec: ShardSpec,
    *,
    timeout_seconds: int,
    executor: str,
) -> ShardAttemptResult:
    if executor == "cli":
        return _run_cli_shard_attempt(spec, timeout_seconds)
    if executor == "sdk":
        return _run_sdk_shard_attempt(run_dir, spec, timeout_seconds)
    if executor == "sdk-cli-fallback":
        try:
            return _run_sdk_shard_attempt(run_dir, spec, timeout_seconds)
        except TimeoutError as error:
            if expected_outputs_exist(run_dir, spec):
                return ShardAttemptResult(
                    returncode=0,
                    stdout="",
                    stderr=(
                        "SDK executor timed out after producing expected outputs; "
                        f"accepting artifacts. SDK error: {error}"
                    ),
                    executor="sdk",
                )
            result = _run_cli_shard_attempt(spec, timeout_seconds)
            fallback_note = (
                "SDK executor timed out waiting for app-server notifications; "
                f"retried with CLI executor. SDK error: {error}"
            )
            result.stderr = "\n".join(part for part in (fallback_note, result.stderr) if part)
            return result
    raise ValueError(f"unknown executor: {executor}")


def _run_single_shard(
    run_dir: Path,
    spec: ShardSpec,
    *,
    max_retries: int = 1,
    timeout_seconds: int = DEFAULT_SHARD_TIMEOUT_SECONDS,
    executor: str = DEFAULT_EXECUTOR,
    force: bool = False,
) -> None:
    _validate_shard_spec(spec)
    if not force and expected_outputs_exist(run_dir, spec):
        return

    shard_completed = False
    start_attempt = _next_shard_attempt(run_dir, spec)
    for attempt in range(start_attempt, start_attempt + max_retries + 1):
        shard_dir = _shard_dir(run_dir, spec)
        stdout_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
        stderr_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
        try:
            result = _run_shard_attempt(
                run_dir,
                spec,
                timeout_seconds=timeout_seconds,
                executor=executor,
            )
        except (OSError, subprocess.TimeoutExpired, Exception) as error:
            sdk_meta = getattr(error, "sdk_meta", None)
            sdk_thread = sdk_meta.get("thread_id") if isinstance(sdk_meta, dict) else "n/a"
            sdk_turn = sdk_meta.get("turn_id") if isinstance(sdk_meta, dict) else "n/a"
            stderr = (
                f"sdk_thread={sdk_thread} sdk_turn={sdk_turn}\n"
                + "".join(
                    traceback.format_exception(type(error), error, error.__traceback__)
                )
            )
            result = ShardAttemptResult(
                returncode=None,
                stdout="",
                stderr=stderr,
                executor=executor,
            )
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")

        status = (
            "completed"
            if result.returncode == 0 and expected_outputs_exist(run_dir, spec)
            else "failed"
        )
        _write_shard_manifest(
            run_dir,
            spec,
            attempt=attempt,
            status=status,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        _append_sdk_thread_index(
            run_dir,
            spec,
            attempt=attempt,
            status=status,
            result=result,
        )
        if status == "completed":
            shard_completed = True
            break

    if not shard_completed:
        append_run_log(
            run_dir,
            spec.stage,
            "failed",
            f"{spec.shard_id} missing expected outputs",
        )
        raise RuntimeError(
            f"Shard {spec.stage}/{spec.shard_id} did not produce expected outputs"
        )


def run_shards(
    run_dir: Path,
    specs: list[ShardSpec],
    *,
    max_retries: int = 1,
    timeout_seconds: int = DEFAULT_SHARD_TIMEOUT_SECONDS,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
    force: bool = False,
) -> None:
    if max_workers < 1:
        raise ValueError(f"max_workers must be >= 1, got {max_workers}")
    if executor not in {"sdk", "cli", "sdk-cli-fallback"}:
        raise ValueError(f"unknown executor: {executor}")
    pending = []
    for spec in specs:
        _validate_shard_spec(spec)
        if force or not expected_outputs_exist(run_dir, spec):
            pending.append(spec)

    if max_workers == 1 or len(pending) <= 1:
        for spec in pending:
            _run_single_shard(
                run_dir,
                spec,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                executor=executor,
                force=force,
            )
        return

    failures: list[BaseException] = []
    worker_count = min(max_workers, len(pending))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _run_single_shard,
                run_dir,
                spec,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                executor=executor,
                force=force,
            ): spec
            for spec in pending
        }
        for future in as_completed(futures):
            try:
                future.result()
            except BaseException as error:
                failures.append(error)
    if failures:
        recovery_failures: list[BaseException] = []
        recovery_specs = [spec for spec in pending if not expected_outputs_exist(run_dir, spec)]
        for spec in recovery_specs:
            append_run_log(
                run_dir,
                spec.stage,
                "recovery",
                f"{spec.shard_id} retrying serially after parallel failure",
            )
            try:
                _run_single_shard(
                    run_dir,
                    spec,
                    max_retries=max_retries,
                    timeout_seconds=timeout_seconds,
                    executor=executor,
                    force=force,
                )
                append_run_log(
                    run_dir,
                    spec.stage,
                    "recovered",
                    f"{spec.shard_id} completed during serial recovery",
                )
            except BaseException as error:
                recovery_failures.append(error)
        if not recovery_failures:
            return
        raise RuntimeError(
            f"{len(recovery_failures)} shard(s) failed after serial recovery; "
            f"first failure: {recovery_failures[0]}"
        ) from recovery_failures[0]


def _stage_max_workers_env_name(stage: str) -> str:
    safe_stage = re.sub(r"[^A-Za-z0-9]+", "_", str(stage)).strip("_")
    return f"SWARN_STAGE_{safe_stage}_MAX_EFFECTIVE_WORKERS"


def _effective_max_workers(requested_workers: int, *, stage: str | None = None) -> int:
    raw_cap = os.environ.get("SWARN_MAX_EFFECTIVE_WORKERS")
    if raw_cap is None:
        cap = DEFAULT_MAX_EFFECTIVE_WORKERS
    else:
        try:
            cap = int(raw_cap)
        except ValueError as error:
            raise ValueError("SWARN_MAX_EFFECTIVE_WORKERS must be an integer") from error
    if cap < 1:
        raise ValueError("SWARN_MAX_EFFECTIVE_WORKERS must be >= 1")
    if stage is not None:
        stage_key = str(stage)
        env_name = _stage_max_workers_env_name(stage_key)
        raw_stage_cap = os.environ.get(env_name)
        if raw_stage_cap is not None:
            try:
                stage_cap = int(raw_stage_cap)
            except ValueError as error:
                raise ValueError(f"{env_name} must be an integer") from error
            if stage_cap < 1:
                raise ValueError(f"{env_name} must be >= 1")
        else:
            stage_cap = DEFAULT_STAGE_MAX_EFFECTIVE_WORKERS.get(stage_key)
        if stage_cap is not None:
            if stage_cap < 1:
                raise ValueError(f"default cap for stage {stage_key} must be >= 1")
            cap = min(cap, stage_cap)
    return min(requested_workers, cap)


def run_deterministic_command(run_dir: Path, stage: str, cmd: list[str]) -> None:
    detail = " ".join(cmd)
    try:
        completed = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    except OSError as error:
        append_run_log(run_dir, stage, "failed", detail)
        stage_dir = ensure_run_control(run_dir) / "stages" / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "last_stdout.txt").write_text("")
        (stage_dir / "last_stderr.txt").write_text(f"{type(error).__name__}: {error}\n")
        raise RuntimeError(f"stage {stage} command failed: {detail}") from error

    if completed.returncode != 0:
        append_run_log(run_dir, stage, "failed", detail)
        stage_dir = ensure_run_control(run_dir) / "stages" / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "last_stdout.txt").write_text(completed.stdout or "")
        (stage_dir / "last_stderr.txt").write_text(completed.stderr or "")
        raise RuntimeError(f"stage {stage} command failed: {detail}")
    append_run_log(run_dir, stage, "completed", detail)
