from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import DEFAULT_EXECUTOR, RUNS_ROOT
from scripts.auto_research_runner.io_utils import _safe_component
from scripts.auto_research_runner.process_cleanup import (
    cleanup_stage_6_research_mcp_processes,
)
from scripts.auto_research_runner.shards import _effective_max_workers
from scripts.auto_research_runner.stages import (
    run_stage_1,
    run_stage_2,
    run_stage_3,
    run_stage_4,
    run_stage_5,
    run_stage_6,
    run_stage_7,
    run_stage_8,
    run_stage_9,
    run_stage_10,
    run_stage_11,
    run_stage_12,
    run_stage_12_5,
    run_stage_13,
    run_stage_14,
    run_stage_15,
    run_stage_16,
    run_stage_17,
    run_stage_18,
    run_stage_19,
    start_new_run,
)
from scripts.auto_research_runner.state import (
    append_run_log,
    load_run_state,
    save_run_state,
)
from scripts.auto_research_runner.validation import validate_stage_1_keep_all_contract


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare an auto-research durable run.")
    parser.add_argument("--topic")
    parser.add_argument("--run-id")
    parser.add_argument("--phase", choices=("draft", "write", "all"), default="all")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--from-stage")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument(
        "--executor",
        choices=("sdk", "cli", "sdk-cli-fallback"),
        default=DEFAULT_EXECUTOR,
    )
    parser.add_argument("--status", action="store_true")
    return parser.parse_args(argv)


def _run_stage_handler(
    handler: Any,
    run_dir: Path,
    *,
    max_workers: int,
    executor: str,
) -> None:
    parameters = inspect.signature(handler).parameters
    kwargs: dict[str, Any] = {}
    if "max_workers" in parameters:
        kwargs["max_workers"] = max_workers
    if "executor" in parameters:
        kwargs["executor"] = executor
    handler(run_dir, **kwargs)


def _validate_stage_1_before_later_start(run_dir: Path, start: str) -> None:
    try:
        start_stage = float(start)
    except ValueError:
        return
    if start_stage > 1:
        validate_stage_1_keep_all_contract(run_dir)


def _latest_shard_manifest(run_dir: Path) -> dict[str, Any] | None:
    latest: tuple[float, dict[str, Any]] | None = None
    for path in (run_dir / "run_control" / "stages").glob("*/*/*.json"):
        if path.parent.name != "shards":
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        data["_manifest_path"] = str(path.relative_to(run_dir))
        item = (path.stat().st_mtime, data)
        if latest is None or item[0] > latest[0]:
            latest = item
    return latest[1] if latest else None


def format_run_status(run_dir: Path) -> str:
    state = load_run_state(run_dir)
    shard = _latest_shard_manifest(run_dir)
    lines = [
        f"run_id={run_dir.name}",
        f"status={state.get('status', 'unknown')}",
        f"current_stage={state.get('current_stage', '')}",
        f"last_completed_stage={state.get('last_completed_stage', '')}",
    ]
    if state.get("status") in {"failed", "interrupted"}:
        lines.append(f"failed_stage={state.get('failed_stage', '')}")
        lines.append(f"error_type={state.get('error_type', '')}")
        lines.append(f"error={state.get('error', '')}")
    if shard:
        if shard.get("status") == "failed":
            lines.append(f"failed_stage={shard.get('stage', '')}")
            lines.append(f"failed_shard={shard.get('shard_id', '')}")
        else:
            lines.append(f"latest_stage={shard.get('stage', '')}")
            lines.append(f"latest_shard={shard.get('shard_id', '')}")
        lines.append(f"executor={shard.get('executor', '')}")
        lines.append(f"thread_id={shard.get('thread_id') or ''}")
        lines.append(f"turn_id={shard.get('turn_id') or ''}")
        lines.append(f"manifest={shard.get('_manifest_path', '')}")
        lines.append(f"stderr={shard.get('stderr_path') or ''}")
    return "\n".join(lines) + "\n"


def _record_run_failure(
    run_dir: Path,
    *,
    stage: str,
    error: BaseException,
    status: str = "failed",
) -> None:
    error_text = str(error) or repr(error)
    save_run_state(
        run_dir,
        {
            **load_run_state(run_dir),
            "status": status,
            "current_stage": stage,
            "failed_stage": stage,
            "error_type": type(error).__name__,
            "error": error_text,
        },
    )
    append_run_log(run_dir, stage, status, f"{type(error).__name__}: {error_text}")


def _clear_failure_fields(state: dict[str, object]) -> dict[str, object]:
    state.pop("failed_stage", None)
    state.pop("error_type", None)
    state.pop("error", None)
    return state


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_workers < 1:
        raise SystemExit("--max-workers must be >= 1")
    if args.status:
        if not args.run_id:
            raise SystemExit("--status requires --run-id")
        _safe_component(args.run_id, field="run_id")
        run_dir = RUNS_ROOT / args.run_id
        if not run_dir.exists():
            raise SystemExit(f"run directory does not exist: {run_dir}")
        print(format_run_status(run_dir), end="")
        return 0
    if not args.topic and not args.run_id:
        raise SystemExit("one of --topic or --run-id is required")
    if args.topic and not args.run_id and args.phase == "write":
        raise SystemExit("--topic cannot be used with --phase write; use draft or all")

    run_id = args.run_id
    topic_bootstrap = run_id is None
    if run_id is None:
        run_id = start_new_run(args.topic, args.phase)
    _safe_component(run_id, field="run_id")
    run_dir = RUNS_ROOT / run_id
    if not run_dir.exists():
        raise SystemExit(f"run directory does not exist: {run_dir}")

    state = load_run_state(run_dir)
    bootstrap_handlers = [
        ("1", run_stage_1),
        ("2", run_stage_2),
        ("3", run_stage_3),
        ("4", run_stage_4),
        ("5", run_stage_5),
        ("6", run_stage_6),
        ("7", run_stage_7),
        ("8", run_stage_8),
        ("9", run_stage_9),
        ("10", run_stage_10),
    ]
    draft_handlers = [
        ("11", run_stage_11),
        ("12", run_stage_12),
        ("12.5", run_stage_12_5),
        ("13", run_stage_13),
    ]
    write_handlers = [
        ("14", run_stage_14),
        ("15", run_stage_15),
        ("16", run_stage_16),
        ("17", run_stage_17),
        ("18", run_stage_18),
        ("19", run_stage_19),
    ]
    requested_start = args.from_stage or (state.get("current_stage") if args.resume else None)
    requested_stage_num: float | None = None
    if requested_start is not None:
        try:
            requested_stage_num = float(str(requested_start))
        except ValueError:
            requested_stage_num = None

    include_bootstrap = topic_bootstrap or (
        args.resume and requested_stage_num is not None and requested_stage_num <= 10
    )

    if args.phase == "draft":
        handlers = (bootstrap_handlers + draft_handlers) if include_bootstrap else draft_handlers
    elif args.phase == "write":
        handlers = write_handlers
    else:
        handlers = (bootstrap_handlers if include_bootstrap else []) + draft_handlers + write_handlers

    default_start = handlers[0][0]
    start = requested_start or default_start
    handler_stages = {stage for stage, _ in handlers}
    if start not in handler_stages:
        raise SystemExit(f"stage {start} is not available for phase {args.phase}")
    try:
        _validate_stage_1_before_later_start(run_dir, start)
        state.update(
            {
                "run_id": run_id,
                "phase": args.phase,
                "topic": args.topic or state.get("topic", ""),
                "status": "running",
                "current_stage": start,
                "resume": args.resume,
            }
        )
        _clear_failure_fields(state)
        save_run_state(run_dir, state)

        active = False
        current_stage = start
        for stage, handler in handlers:
            if stage == start:
                active = True
            if not active:
                continue

            current_stage = stage
            save_run_state(
                run_dir,
                {**load_run_state(run_dir), "current_stage": stage, "status": "running"},
            )
            try:
                max_workers = _effective_max_workers(args.max_workers, stage=stage)
            except ValueError as error:
                raise SystemExit(str(error)) from error
            try:
                _run_stage_handler(
                    handler,
                    run_dir,
                    max_workers=max_workers,
                    executor=args.executor,
                )
            finally:
                if stage == "6":
                    cleanup_stage_6_research_mcp_processes(run_dir)
            save_run_state(
                run_dir,
                {**load_run_state(run_dir), "last_completed_stage": stage},
            )
    except KeyboardInterrupt as error:
        _record_run_failure(
            run_dir,
            stage=current_stage if "current_stage" in locals() else start,
            error=error,
            status="interrupted",
        )
        raise
    except Exception as error:
        _record_run_failure(run_dir, stage=current_stage if "current_stage" in locals() else start, error=error)
        raise

    save_run_state(
        run_dir,
        _clear_failure_fields({**load_run_state(run_dir), "status": "completed"}),
    )
    print(f"{args.phase} phase complete. run_id={run_id}")
    return 0
