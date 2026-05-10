from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "research_runs"
DEFAULT_SHARD_TIMEOUT_SECONDS = 3600

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


@dataclass
class ShardSpec:
    stage: str
    shard_id: str
    agent: str
    model: str
    prompt: str
    expected_outputs: list[str]


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


def _safe_component(value: str, *, field: str) -> str:
    path = Path(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {"", ".", ".."}:
        raise ValueError(f"unsafe {field}: {value}")
    return value


def _safe_relative_path(value: str, *, field: str) -> Path:
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe {field}: {value}")
    return path


def _validate_shard_spec(spec: ShardSpec) -> None:
    _safe_component(spec.stage, field="stage")
    _safe_component(spec.shard_id, field="shard_id")
    for rel in spec.expected_outputs:
        _safe_relative_path(rel, field="expected output")


def verified_graph_fragment_filename(arxiv_id: str) -> str:
    return f"{quote(str(arxiv_id), safe='')}.json"


def verified_graph_fragment_relpath(arxiv_id: str) -> str:
    return f"11_verified_graph/fragments/{verified_graph_fragment_filename(arxiv_id)}"


def _stable_stage_11_shard_id(arxiv_id: str) -> str:
    stem = verified_graph_fragment_filename(arxiv_id).removesuffix(".json")
    safe_stem = stem.replace("%", "pct")
    return f"vgraph-resume-{safe_stem}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare an auto-research durable run.")
    parser.add_argument("--topic")
    parser.add_argument("--run-id")
    parser.add_argument("--phase", choices=("draft", "write", "all"), default="all")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--from-stage")
    return parser.parse_args(argv)


def _edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        edge.get("src"),
        edge.get("dst"),
        edge.get("type"),
        edge.get("source_node_id"),
        tuple(edge.get("source_lines", ())),
    )


def merge_verified_graph_fragments(run_dir: Path) -> dict[str, Any]:
    fragments_dir = run_dir / "11_verified_graph" / "fragments"
    if not fragments_dir.exists():
        raise FileNotFoundError(f"missing Stage 11 fragments directory: {fragments_dir}")

    fragment_paths = sorted(fragments_dir.glob("*.json"))
    if not fragment_paths:
        raise ValueError(f"no Stage 11 fragment JSON files found in {fragments_dir}")

    nodes_by_id: dict[Any, dict[str, Any]] = {}
    edges_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}

    for fragment_path in fragment_paths:
        fragment = json.loads(fragment_path.read_text())
        for node in fragment.get("nodes", []):
            node_id = node.get("id")
            if not node_id:
                raise ValueError(f"node missing id in {fragment_path}")
            if node_id not in nodes_by_id:
                nodes_by_id[node_id] = node
        for edge in fragment.get("edges", []):
            if edge.get("confidence") != "verified":
                raise ValueError(f"unverified edge in {fragment_path}")
            if not edge.get("source_node_id"):
                raise ValueError(f"edge missing source_node_id in {fragment_path}")
            if not edge.get("source_lines"):
                raise ValueError(f"edge missing source_lines in {fragment_path}")
            key = _edge_key(edge)
            if key not in edges_by_key:
                edges_by_key[key] = edge

    return {
        "nodes": sorted(nodes_by_id.values(), key=lambda node: node["id"]),
        "edges": [edges_by_key[key] for key in sorted(edges_by_key)],
    }


def _load_weak_edge_count(run_dir: Path) -> int:
    weak_graph_path = run_dir / "05_weak_graph" / "weak_global_graph.json"
    if not weak_graph_path.exists():
        return 0
    weak_graph = json.loads(weak_graph_path.read_text())
    return len(weak_graph.get("edges", []))


def run_stage_11_merge(run_dir: Path) -> None:
    graph = merge_verified_graph_fragments(run_dir)
    verified_graph_dir = run_dir / "11_verified_graph"
    verified_graph_dir.mkdir(parents=True, exist_ok=True)

    global_graph_path = verified_graph_dir / "global_graph.json"
    global_graph_tmp_path = verified_graph_dir / "global_graph.json.tmp"
    global_graph_tmp_path.write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n")
    global_graph_tmp_path.replace(global_graph_path)

    verified_edges = len(graph["edges"])
    weak_edges = _load_weak_edge_count(run_dir)
    dropped = max(weak_edges - verified_edges, 0)
    report = "\n".join(
        [
            "# Verified graph report",
            "",
            f"- Nodes: {len(graph['nodes'])}",
            f"- Verified edges: {verified_edges}",
            f"- Weak edges not promoted: {dropped}",
            "",
        ]
    )
    report_path = verified_graph_dir / "graph_report.md"
    report_tmp_path = verified_graph_dir / "graph_report.md.tmp"
    report_tmp_path.write_text(report)
    report_tmp_path.replace(report_path)

    append_run_log(run_dir, "11", "merged", f"{verified_edges} verified edges")


def expected_outputs_exist(run_dir: Path, spec: ShardSpec) -> bool:
    _validate_shard_spec(spec)
    return all(
        (run_dir / _safe_relative_path(rel, field="expected output")).exists()
        for rel in spec.expected_outputs
    )


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
    returncode: int | None,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    path = _shard_dir(run_dir, spec) / f"{spec.shard_id}.json"
    payload = {
        "stage": spec.stage,
        "shard_id": spec.shard_id,
        "agent": spec.agent,
        "model": spec.model,
        "attempt": attempt,
        "expected_outputs": spec.expected_outputs,
        "status": status,
        "returncode": returncode,
        "stdout_path": str(stdout_path.relative_to(run_dir)),
        "stderr_path": str(stderr_path.relative_to(run_dir)),
        "updated_at": now_iso(),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def _codex_exec_command(spec: ShardSpec) -> list[str]:
    return [
        "codex",
        "exec",
        "--cd",
        str(REPO_ROOT),
        "--model",
        spec.model,
        "--ask-for-approval",
        "never",
        spec.prompt,
    ]


def run_shards(
    run_dir: Path,
    specs: list[ShardSpec],
    *,
    max_retries: int = 1,
    timeout_seconds: int = DEFAULT_SHARD_TIMEOUT_SECONDS,
) -> None:
    for spec in specs:
        _validate_shard_spec(spec)
        if expected_outputs_exist(run_dir, spec):
            continue

        shard_completed = False
        for attempt in range(1, max_retries + 2):
            shard_dir = _shard_dir(run_dir, spec)
            stdout_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
            stderr_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
            returncode = None
            with stdout_path.open("w") as out, stderr_path.open("w") as err:
                try:
                    completed = subprocess.run(
                        _codex_exec_command(spec),
                        cwd=REPO_ROOT,
                        text=True,
                        stdout=out,
                        stderr=err,
                        timeout=timeout_seconds,
                    )
                    returncode = completed.returncode
                except (OSError, subprocess.TimeoutExpired) as error:
                    err.write(f"{type(error).__name__}: {error}\n")

            status = (
                "completed"
                if returncode == 0 and expected_outputs_exist(run_dir, spec)
                else "failed"
            )
            _write_shard_manifest(
                run_dir,
                spec,
                attempt=attempt,
                status=status,
                returncode=returncode,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
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


def load_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    path = run_dir / "07_scoring" / "promoted_papers.json"
    data = json.loads(path.read_text())
    return [str(item["arxiv_id"]) for item in data.get("promoted_papers", [])]


def _stage_11_prompt(run_id: str, shard_id: str, arxiv_ids: list[str]) -> str:
    output_files = {
        arxiv_id: f"11_verified_graph/fragments/{verified_graph_fragment_filename(arxiv_id)}"
        for arxiv_id in arxiv_ids
    }
    return "\n".join(
        [
            "Read AGENTS.md first.",
            "Run Stage 11 verified graph extraction only.",
            f"run_id={run_id}",
            f"shard_id={shard_id}",
            f"arxiv_ids={arxiv_ids}",
            "Follow .codex/agents/verified_graph_extractor.toml and .agents/skills/verified-graph-extraction/SKILL.md.",
            "Read 10_verified_evidence and 05_weak_graph/fragments for these ids.",
            "Write only the 11_verified_graph/fragments/{arxiv_id}.json fragment files named below.",
            f"Use these exact output files: {output_files}",
            "Do not write 11_verified_graph/global_graph.json.",
            "Return the standard short success string.",
        ]
    )


def run_stage_11(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "11"):
        append_run_log(run_dir, "11", "skipped", "global graph already present")
        return

    run_id = run_dir.name
    promoted = load_promoted_arxiv_ids(run_dir)
    missing = [
        aid
        for aid in promoted
        if not (run_dir / verified_graph_fragment_relpath(aid)).exists()
    ]
    specs = [
        ShardSpec(
            stage="11",
            shard_id=_stable_stage_11_shard_id(aid),
            agent="verified_graph_extractor",
            model="gpt-5.4-mini",
            prompt=_stage_11_prompt(run_id, _stable_stage_11_shard_id(aid), [aid]),
            expected_outputs=[verified_graph_fragment_relpath(aid)],
        )
        for aid in missing
    ]
    if specs:
        append_run_log(run_dir, "11", "dispatching", f"{len(specs)} missing fragments")
        run_shards(run_dir, specs)

    still_missing = [
        aid
        for aid in promoted
        if not (run_dir / verified_graph_fragment_relpath(aid)).exists()
    ]
    if still_missing:
        raise RuntimeError(f"Stage 11 still missing fragments: {still_missing}")
    run_stage_11_merge(run_dir)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.topic and not args.run_id:
        raise SystemExit("one of --topic or --run-id is required")

    run_id = args.run_id or "pending-topic-run"
    run_dir = RUNS_ROOT / run_id
    ensure_run_control(run_dir)
    state = load_run_state(run_dir)
    topic = args.topic or state.get("topic", "")
    if args.resume:
        current_stage = args.from_stage or state.get("current_stage", "0")
        last_completed_stage = state.get("last_completed_stage")
    else:
        current_stage = args.from_stage or "0"
        last_completed_stage = None

    save_run_state(
        run_dir,
        {
            "run_id": run_id,
            "phase": args.phase,
            "topic": topic,
            "status": "ready",
            "current_stage": current_stage,
            "last_completed_stage": last_completed_stage,
            "resume": args.resume,
        },
    )
    print("runner ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
