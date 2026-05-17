from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShardSpec:
    stage: str
    shard_id: str
    agent: str
    model: str
    prompt: str
    expected_outputs: list[str]


@dataclass
class ShardAttemptResult:
    returncode: int | None
    stdout: str
    stderr: str
    executor: str
    thread_id: str | None = None
    turn_id: str | None = None


class Stage8MarkdownUnavailable(RuntimeError):
    """Raised when upstream answers but has no usable markdown for a paper."""
