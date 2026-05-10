from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "research_runs"

PRIMARY_ARTIFACTS = {
    "0": ("run_config.json",),
    "1": ("00_input/search_plan.json", "02_paper_pool/paper_pool.json"),
    "3": ("05_weak_graph/weak_global_graph.json",),
    "4": ("06_expansion/known_concepts_snapshot.json",),
    "5": (
        "06_expansion/knowledge_gap_report.json",
        "06_expansion/expansion_need_queue.json",
    ),
    "6": ("06_expansion/expansion_round_01.json",),
    "7": ("07_scoring/promoted_papers.json",),
    "11": ("11_verified_graph/global_graph.json", "11_verified_graph/graph_report.md"),
    "12": ("12_taxonomy/outline.json",),
    "15": ("15_verification/verification_summary.csv",),
    "16": ("16_book/chapters_manifest.json",),
    "17": ("17_learning_suggestions/knowledge_to_add.md",),
    "18": (
        "16_book/SUMMARY.md",
        "16_book/sidebar.json",
        "16_book/appendices/references.md",
    ),
}


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


def primary_artifact_exists(run_dir: Path, stage: str) -> bool:
    artifacts = PRIMARY_ARTIFACTS.get(str(stage), ())
    return bool(artifacts) and all((run_dir / artifact).exists() for artifact in artifacts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare an auto-research durable run.")
    parser.add_argument("--topic")
    parser.add_argument("--run-id")
    parser.add_argument("--phase", choices=("draft", "write", "all"), default="all")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--from-stage")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.topic and not args.run_id:
        raise SystemExit("one of --topic or --run-id is required")

    run_id = args.run_id or "pending-topic-run"
    run_dir = RUNS_ROOT / run_id
    ensure_run_control(run_dir)
    state = load_run_state(run_dir)
    save_run_state(
        run_dir,
        {
            "run_id": run_id,
            "phase": args.phase,
            "topic": args.topic or state.get("topic", ""),
            "status": "ready",
            "current_stage": args.from_stage or state.get("current_stage", "0"),
            "last_completed_stage": state.get("last_completed_stage"),
            "resume": args.resume,
        },
    )
    print("runner ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
