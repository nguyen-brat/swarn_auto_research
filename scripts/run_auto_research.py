from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from swarn_research_mcp.research_book import BOOK_FILE_BY_ID


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
        "14_chapters/book/appendices/references.md",
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


def run_stage_12_5(run_dir: Path) -> None:
    run_deterministic_command(
        run_dir,
        "12.5",
        [
            sys.executable,
            "-m",
            "swarn_research_mcp.research_book",
            str(run_dir),
            "--normalize-outline",
        ],
    )


def run_stage_18(run_dir: Path) -> None:
    run_deterministic_command(
        run_dir,
        "18",
        [
            sys.executable,
            "-m",
            "swarn_research_mcp.research_book",
            str(run_dir),
            "--generate",
        ],
    )
    run_deterministic_command(
        run_dir,
        "18",
        [
            sys.executable,
            "-m",
            "swarn_research_mcp.research_book",
            str(run_dir),
            "--validate",
        ],
    )
    if not primary_artifact_exists(run_dir, "18"):
        raise RuntimeError("Stage 18 did not produce book artifacts")


def load_outline(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())


def build_chapter_targets(run_dir: Path) -> list[dict[str, str]]:
    outline = load_outline(run_dir)
    targets: list[dict[str, str]] = []
    for section in outline.get("book_sections", []):
        if section["id"] == "appendices":
            continue
        target = {"type": "book", "id": section["id"]}
        _validate_chapter_target(target)
        targets.append(target)
    for family in outline.get("families", []):
        if family.get("is_group") or family["id"] == "standalone":
            continue
        target = {"type": "families", "id": family["id"]}
        _validate_chapter_target(target)
        targets.append(target)
    for method in outline.get("methods", []):
        target = {"type": "methods", "id": method["id"]}
        _validate_chapter_target(target)
        targets.append(target)
    return targets


def _validate_chapter_target(target: dict[str, str]) -> None:
    target_type = target["type"]
    if target_type not in {"book", "families", "methods"}:
        raise ValueError(f"unsafe target type: {target_type}")
    _safe_component(target["id"], field="target id")


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _generic_agent_prompt(
    agent_toml: str,
    run_id: str,
    stage: str,
    shard_id: str,
    payload: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Read AGENTS.md first.",
            f"Run Stage {stage} only.",
            f"run_id={run_id}",
            f"shard_id={shard_id}",
            f"payload={json.dumps(payload, sort_keys=True)}",
            f"Follow {agent_toml} exactly.",
            "Write only the artifacts required by that agent and shard.",
            "Return the standard short success string.",
        ]
    )


def run_stage_12(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "12"):
        append_run_log(run_dir, "12", "skipped", "outline already present")
        return
    expected_outputs = [
        "12_taxonomy/communities.json",
        "12_taxonomy/taxonomy.json",
        "12_taxonomy/outline.json",
    ]
    spec = ShardSpec(
        stage="12",
        shard_id="outline",
        agent="outline_planner",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/outline_planner.toml",
            run_dir.name,
            "12",
            "outline",
            {"expected_outputs": expected_outputs},
        ),
        expected_outputs=expected_outputs,
    )
    run_shards(run_dir, [spec])


def _expected_chapter_pack(target: dict[str, str]) -> str:
    _validate_chapter_target(target)
    return f"13_chapter_packs/{target['type']}/{target['id']}_pack.json"


def _expected_chapter_file(target: dict[str, str]) -> str:
    _validate_chapter_target(target)
    if target["type"] == "book":
        filename = BOOK_FILE_BY_ID.get(target["id"], f"{target['id']}.md")
        return f"14_chapters/book/{filename}"
    return f"14_chapters/{target['type']}/{target['id']}.md"


def _expected_verification_file(target: dict[str, str]) -> str:
    _validate_chapter_target(target)
    return f"15_verification/{target['type']}/{target['id']}_verification.json"


def run_stage_13(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    specs = [
        ShardSpec(
            stage="13",
            shard_id=f"pack-{idx:03d}",
            agent="chapter_pack_builder",
            model="gpt-5.4-mini",
            prompt=_generic_agent_prompt(
                ".codex/agents/chapter_pack_builder.toml",
                run_dir.name,
                "13",
                f"pack-{idx:03d}",
                {"targets": chunk},
            ),
            expected_outputs=[_expected_chapter_pack(t) for t in chunk],
        )
        for idx, chunk in enumerate(chunked(targets, 1), start=1)
        if any(not (run_dir / _expected_chapter_pack(t)).exists() for t in chunk)
    ]
    if specs:
        run_shards(run_dir, specs)


def run_stage_14(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    specs = []
    agent_by_type = {
        "book": "book_section_writer",
        "families": "family_chapter_writer",
        "methods": "method_chapter_writer",
    }
    for target_type in ("book", "families", "methods"):
        typed_targets = [t for t in targets if t["type"] == target_type]
        for idx, chunk in enumerate(chunked(typed_targets, 2), start=1):
            if all((run_dir / _expected_chapter_file(t)).exists() for t in chunk):
                continue
            agent = agent_by_type[target_type]
            shard_id = f"write-{target_type}-{idx:03d}"
            specs.append(
                ShardSpec(
                    stage="14",
                    shard_id=shard_id,
                    agent=agent,
                    model="gpt-5.4",
                    prompt=_generic_agent_prompt(
                        f".codex/agents/{agent}.toml",
                        run_dir.name,
                        "14",
                        shard_id,
                        {"targets": chunk},
                    ),
                    expected_outputs=[_expected_chapter_file(t) for t in chunk],
                )
            )
    if specs:
        run_shards(run_dir, specs)


def run_stage_15(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    specs = [
        ShardSpec(
            stage="15",
            shard_id=f"verify-{idx:03d}",
            agent="verifier",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(
                ".codex/agents/verifier.toml",
                run_dir.name,
                "15",
                f"verify-{idx:03d}",
                {"targets": chunk},
            ),
            expected_outputs=[_expected_verification_file(t) for t in chunk],
        )
        for idx, chunk in enumerate(chunked(targets, 2), start=1)
        if any(not (run_dir / _expected_verification_file(t)).exists() for t in chunk)
    ]
    if specs:
        run_shards(run_dir, specs)
    _write_verification_summary(run_dir, targets)


def _write_verification_summary(run_dir: Path, targets: list[dict[str, str]]) -> None:
    summary_dir = run_dir / "15_verification"
    summary_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for target in targets:
        path = run_dir / _expected_verification_file(target)
        if not path.exists():
            raise RuntimeError(f"Stage 15 missing verification file: {path}")
        data = json.loads(path.read_text())
        summary = data.get("summary", {})
        rows.append(
            {
                "target_type": target["type"],
                "target_id": target["id"],
                "passed": data.get("passed"),
                "claims_total": summary.get("claims_total", 0),
                "claims_unsupported": summary.get("claims_unsupported", 0),
                "claims_overstated": summary.get("claims_overstated", 0),
                "gaps_covered": summary.get("gaps_covered", 0),
                "gaps_missing": summary.get("gaps_missing", 0),
                "word_count": summary.get("word_count", 0),
                "form_issue_count": summary.get("form_issue_count", 0),
                "equations_rendered": summary.get("equations_rendered", 0),
                "pseudocode_blocks": summary.get("pseudocode_blocks", 0),
            }
        )
    summary_path = summary_dir / "verification_summary.csv"
    tmp_path = summary_dir / "verification_summary.csv.tmp"
    with tmp_path.open("w", newline="") as handle:
        fieldnames = [
            "target_type",
            "target_id",
            "passed",
            "claims_total",
            "claims_unsupported",
            "claims_overstated",
            "gaps_covered",
            "gaps_missing",
            "word_count",
            "form_issue_count",
            "equations_rendered",
            "pseudocode_blocks",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(summary_path)


def run_stage_16(run_dir: Path) -> None:
    targets = build_chapter_targets(run_dir)
    shard_paths: list[str] = []
    specs = []
    for idx, chunk in enumerate(chunked(targets, 2), start=1):
        shard_id = f"manifest-{idx:03d}"
        shard_path = f"16_book/chapters_manifest_shard_{shard_id}.json"
        shard_paths.append(shard_path)
        if (run_dir / shard_path).exists():
            continue
        specs.append(
            ShardSpec(
                stage="16",
                shard_id=shard_id,
                agent="chapter_manifest_builder",
                model="gpt-5.4",
                prompt=_generic_agent_prompt(
                    ".codex/agents/chapter_manifest_builder.toml",
                    run_dir.name,
                    "16",
                    shard_id,
                    {"targets": chunk},
                ),
                expected_outputs=[shard_path],
            )
        )
    if specs:
        run_shards(run_dir, specs)
    _merge_chapter_manifest_shards(run_dir, shard_paths)


def _merge_chapter_manifest_shards(run_dir: Path, shard_paths: list[str]) -> None:
    manifest_dir = run_dir / "16_book"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    chapters: list[dict[str, Any]] = []
    for rel_path in shard_paths:
        path = run_dir / rel_path
        if not path.exists():
            raise RuntimeError(f"Stage 16 missing manifest shard: {path}")
        shard_data = json.loads(path.read_text())
        if not isinstance(shard_data, list):
            raise RuntimeError(f"Stage 16 manifest shard is not a list: {path}")
        chapters.extend(shard_data)
    manifest_path = manifest_dir / "chapters_manifest.json"
    tmp_path = manifest_dir / "chapters_manifest.json.tmp"
    tmp_path.write_text(
        json.dumps(
            {"run_id": run_dir.name, "generated_at": now_iso(), "chapters": chapters},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    tmp_path.replace(manifest_path)
    for rel_path in shard_paths:
        (run_dir / rel_path).unlink()


def run_stage_17(run_dir: Path) -> None:
    if primary_artifact_exists(run_dir, "17"):
        append_run_log(
            run_dir, "17", "skipped", "learning suggestions already present"
        )
        return
    spec = ShardSpec(
        stage="17",
        shard_id="learning-suggestions",
        agent="knowledge_gap_detector",
        model="gpt-5.4-mini",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                "Run Stage 17 learning suggestions only.",
                f"run_id={run_dir.name}",
                "Read 06_expansion/knowledge_gap_report.json.",
                "Write 17_learning_suggestions/knowledge_to_add.md.",
                "Do not modify .agents/knowledge_base.md.",
            ]
        ),
        expected_outputs=["17_learning_suggestions/knowledge_to_add.md"],
    )
    run_shards(run_dir, [spec])


def bootstrap_new_run(topic: str, phase: str) -> str:
    prompt = "\n".join(
        [
            "Read AGENTS.md first.",
            "Use .agents/skills/auto-research-orchestrator/SKILL.md.",
            f"Run the auto-research pipeline for this topic through Stage 10 only: {topic}",
            "Stop after Stage 10 verified evidence is complete.",
            "Do not run Stage 11 or later.",
            "Print the final run_id on a line exactly like: RUN_ID=<run_id>",
        ]
    )
    completed = subprocess.run(
        [
            "codex",
            "exec",
            "--cd",
            str(REPO_ROOT),
            "--model",
            "gpt-5.4-mini",
            "--ask-for-approval",
            "never",
            prompt,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"bootstrap failed: {completed.stderr}")
    for line in completed.stdout.splitlines():
        if line.startswith("RUN_ID="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("bootstrap did not print RUN_ID=<run_id>")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.topic and not args.run_id:
        raise SystemExit("one of --topic or --run-id is required")

    run_id = args.run_id
    if run_id is None:
        run_id = bootstrap_new_run(args.topic, args.phase)
    run_dir = RUNS_ROOT / run_id
    if not run_dir.exists():
        raise SystemExit(f"run directory does not exist: {run_dir}")

    state = load_run_state(run_dir)
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
    ]
    if args.phase == "draft":
        handlers = draft_handlers
    elif args.phase == "write":
        handlers = write_handlers
    else:
        handlers = draft_handlers + write_handlers

    default_start = handlers[0][0]
    start = args.from_stage or (state.get("current_stage") if args.resume else None) or default_start
    handler_stages = {stage for stage, _ in handlers}
    if start not in handler_stages:
        raise SystemExit(f"stage {start} is not available for phase {args.phase}")
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
    save_run_state(run_dir, state)

    active = False
    for stage, handler in handlers:
        if stage == start:
            active = True
        if not active:
            continue

        save_run_state(
            run_dir,
            {**load_run_state(run_dir), "current_stage": stage, "status": "running"},
        )
        handler(run_dir)
        save_run_state(
            run_dir,
            {**load_run_state(run_dir), "last_completed_stage": stage},
        )

    save_run_state(run_dir, {**load_run_state(run_dir), "status": "completed"})
    print(f"{args.phase} phase complete. run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
