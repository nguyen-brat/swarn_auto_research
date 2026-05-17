from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_RUN_LOG_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_run_control(run_dir: Path) -> Path:
    run_control = run_dir / "run_control"
    (run_control / "stages").mkdir(parents=True, exist_ok=True)
    return run_control


def load_run_state(run_dir: Path) -> dict[str, Any]:
    state_path = run_dir / "run_control" / "run_state.json"
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text())


def save_run_state(run_dir: Path, state: dict[str, Any]) -> None:
    run_control = ensure_run_control(run_dir)
    state_path = run_control / "run_state.json"
    tmp_path = run_control / "run_state.json.tmp"

    next_state = dict(state)
    next_state["updated_at"] = now_iso()
    tmp_path.write_text(json.dumps(next_state, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(state_path)


def append_run_log(run_dir: Path, stage: str, status: str, detail: str) -> None:
    log_path = run_dir / "run_log.csv"

    with _RUN_LOG_LOCK:
        needs_header = not log_path.exists()

        with log_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=("timestamp", "stage", "status", "detail"))
            if needs_header:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": now_iso(),
                    "stage": stage,
                    "status": status,
                    "detail": detail,
                }
            )
