from __future__ import annotations

import json

import pytest

from scripts.auto_research_runner.contract_repair import (
    RepairIssue,
    append_repair_event,
    preserve_raw_artifact,
)


def test_preserve_raw_artifact_uses_content_addressed_paths(tmp_path):
    run = tmp_path / "run"
    artifact = run / "12_taxonomy" / "outline.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"version": 1}\n')

    first = preserve_raw_artifact(run, artifact)
    artifact.write_text('{"version": 2}\n')
    second = preserve_raw_artifact(run, artifact)

    assert first.raw_artifact != second.raw_artifact
    assert first.raw_sha256 != second.raw_sha256
    assert (run / first.raw_artifact).read_text() == '{"version": 1}\n'
    assert (run / second.raw_artifact).read_text() == '{"version": 2}\n'


def test_preserve_raw_artifact_rejects_path_outside_run(tmp_path):
    run = tmp_path / "run"
    outside = tmp_path / "outside.json"
    outside.write_text("{}")

    with pytest.raises(ValueError, match="outside run directory"):
        preserve_raw_artifact(run, outside)


def test_append_repair_event_writes_jsonl_with_run_relative_paths(tmp_path):
    run = tmp_path / "run"
    artifact = run / "11_verified_graph" / "fragments" / "1.1.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"edges": []}\n')
    raw = preserve_raw_artifact(run, artifact)

    append_repair_event(
        run,
        stage="11",
        artifact_path=artifact,
        raw=raw,
        outcome="accepted",
        issues=[RepairIssue(kind="dropped_invalid_edge", detail="edge source missing")],
    )

    event_path = run / "run_control" / "repairs" / "stage_11" / "repair_events.jsonl"
    event = json.loads(event_path.read_text().strip())
    assert event["stage"] == "11"
    assert event["artifact"] == "11_verified_graph/fragments/1.1.json"
    assert event["raw_artifact"] == raw.raw_artifact
    assert event["raw_sha256"] == raw.raw_sha256
    assert event["outcome"] == "accepted"
    assert event["issues"] == [{"kind": "dropped_invalid_edge", "detail": "edge source missing"}]
