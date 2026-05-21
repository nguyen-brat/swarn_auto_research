from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


RepairOutcome = Literal["attempted", "accepted", "rejected"]


@dataclass(frozen=True)
class RepairIssue:
    kind: str
    detail: str
    before: Any | None = None
    after: Any | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class RawArtifact:
    raw_artifact: str
    raw_sha256: str


def run_relative_path(run_dir: Path, artifact_path: Path) -> Path:
    run_root = run_dir.resolve()
    artifact = artifact_path.resolve()
    try:
        return artifact.relative_to(run_root)
    except ValueError as error:
        raise ValueError(f"artifact path is outside run directory: {artifact_path}") from error


def preserve_raw_artifact(run_dir: Path, artifact_path: Path) -> RawArtifact:
    relpath = run_relative_path(run_dir, artifact_path)
    raw_bytes = artifact_path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    raw_path = run_dir / "run_control" / "repairs" / "raw" / relpath
    raw_path = raw_path.with_name(f"{raw_path.name}.{digest}.json")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.exists():
        raw_path.write_bytes(raw_bytes)
    return RawArtifact(raw_artifact=raw_path.relative_to(run_dir).as_posix(), raw_sha256=digest)


def append_repair_event(
    run_dir: Path,
    *,
    stage: str,
    artifact_path: Path,
    raw: RawArtifact,
    outcome: RepairOutcome,
    issues: list[RepairIssue],
) -> None:
    artifact_relpath = run_relative_path(run_dir, artifact_path).as_posix()
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage),
        "artifact": artifact_relpath,
        "raw_artifact": raw.raw_artifact,
        "raw_sha256": raw.raw_sha256,
        "outcome": outcome,
        "issues": [issue.to_json() for issue in issues],
    }
    stable = json.dumps(
        {key: value for key, value in event.items() if key != "timestamp"},
        sort_keys=True,
        separators=(",", ":"),
    )
    event["event_id"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]

    events_path = run_dir / "run_control" / "repairs" / f"stage_{stage}" / "repair_events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True) + "\n"
    fd = os.open(events_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
