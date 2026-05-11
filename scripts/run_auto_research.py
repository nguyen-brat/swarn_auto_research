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
BOOTSTRAP_TIMEOUT_SECONDS = 6 * 3600
DIRECT_SHARD_RULES = [
    "Execute directly in this codex exec session.",
    "Do not spawn subagents, do not run nested codex commands, and do not wait for other agents.",
    "Do not ask for human input.",
]

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
        "-c",
        'approval_policy="never"',
        "--sandbox",
        "workspace-write",
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
            *DIRECT_SHARD_RULES,
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


METHOD_PACK_SECTION_TITLES = [
    "Summary",
    "Motivation",
    "Intuition",
    "Theory",
    "Algorithm",
    "Example",
    "Interpretation",
    "Strengths",
    "Limitations",
    "Software",
    "Related Methods",
]
METHOD_PACK_REQUIRED_SOURCE_SECTIONS = {"theory", "algorithm", "example", "limitations"}


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
            *DIRECT_SHARD_RULES,
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


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _page_nodes(run_dir: Path, arxiv_id: str) -> dict[str, Any]:
    data = _read_json_or_empty(run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json")
    if isinstance(data.get("nodes"), dict):
        return data["nodes"]
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def _outline_method_maps(outline: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    methods = {method["id"]: method for method in outline.get("methods", [])}
    families = {family["id"]: family for family in outline.get("families", [])}
    return methods, families


def _source_text_from_node(
    run_dir: Path,
    arxiv_id: str,
    node_id: str,
    *,
    fallback_text: str = "",
) -> tuple[str, list[int], str]:
    nodes = _page_nodes(run_dir, arxiv_id)
    node = nodes.get(node_id, {}) if isinstance(nodes, dict) else {}
    lines = [
        int(node.get("start_line") or 0),
        int(node.get("end_line") or node.get("start_line") or 0),
    ]
    section_title = str(node.get("title") or node_id or "source")
    markdown_path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
    if markdown_path.exists() and lines[0] > 0 and lines[1] >= lines[0]:
        markdown_lines = markdown_path.read_text().splitlines()
        text = "\n".join(markdown_lines[lines[0] - 1 : lines[1]]).strip()
        if text:
            return text + "\n", lines, section_title
    summary = str(node.get("summary") or "").strip()
    text = fallback_text.strip() or summary
    return text + ("\n" if text else ""), lines, section_title


def _pack_source_node(
    run_dir: Path,
    arxiv_id: str,
    node_id: str,
    *,
    claim_type: str,
    fallback_text: str = "",
) -> dict[str, Any] | None:
    if not node_id:
        return None
    section_text, lines, section_title = _source_text_from_node(
        run_dir, arxiv_id, node_id, fallback_text=fallback_text
    )
    if not section_text.strip():
        return None
    return {
        "arxiv_id": arxiv_id,
        "node_id": node_id,
        "lines": lines,
        "claim_type": claim_type,
        "section_title": section_title,
        "section_text": section_text,
    }


def _claim_nodes(
    run_dir: Path,
    arxiv_id: str,
    claims: list[dict[str, Any]],
    claim_types: set[str],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for claim in claims:
        claim_type = str(claim.get("claim_type") or "method").lower()
        if claim_types and claim_type not in claim_types:
            continue
        node_id = str(claim.get("source_node_id") or "")
        if not node_id or node_id in seen:
            continue
        source = _pack_source_node(
            run_dir,
            arxiv_id,
            node_id,
            claim_type=claim_type,
            fallback_text=str(claim.get("text") or ""),
        )
        if source:
            seen.add(node_id)
            nodes.append(source)
        if len(nodes) >= limit:
            break
    return nodes


def _structured_nodes(
    run_dir: Path,
    arxiv_id: str,
    items: list[dict[str, Any]],
    *,
    claim_type: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        node_id = str(item.get("source_node_id") or "")
        if not node_id or node_id in seen:
            continue
        fallback = str(item.get("text") or item.get("purpose") or item.get("name") or "")
        source = _pack_source_node(
            run_dir,
            arxiv_id,
            node_id,
            claim_type=claim_type,
            fallback_text=fallback,
        )
        if source:
            seen.add(node_id)
            nodes.append(source)
        if len(nodes) >= limit:
            break
    return nodes


def _first_available_nodes(
    run_dir: Path,
    arxiv_id: str,
    evidence: dict[str, Any],
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    claims = evidence.get("claims") or []
    nodes = _claim_nodes(run_dir, arxiv_id, claims, set(), limit=limit)
    if nodes:
        return nodes
    page_nodes = _page_nodes(run_dir, arxiv_id)
    for node_id in sorted(page_nodes)[:limit]:
        source = _pack_source_node(run_dir, arxiv_id, node_id, claim_type="method")
        if source:
            nodes.append(source)
    return nodes


def _section_nodes(
    run_dir: Path,
    arxiv_id: str,
    evidence: dict[str, Any],
    section_title: str,
) -> list[dict[str, Any]]:
    claims = evidence.get("claims") or []
    section_key = section_title.lower()
    if section_key == "summary":
        nodes = _claim_nodes(run_dir, arxiv_id, claims, {"method", "result", "motivation"}, limit=2)
    elif section_key == "motivation":
        nodes = _claim_nodes(run_dir, arxiv_id, claims, {"motivation"}, limit=2)
    elif section_key == "intuition":
        nodes = _claim_nodes(run_dir, arxiv_id, claims, {"method"}, limit=2)
    elif section_key == "theory":
        nodes = _structured_nodes(
            run_dir, arxiv_id, evidence.get("equations") or [], claim_type="method", limit=3
        )
    elif section_key == "algorithm":
        nodes = _structured_nodes(
            run_dir, arxiv_id, evidence.get("algorithms") or [], claim_type="method", limit=3
        )
    elif section_key == "example":
        nodes = (
            _structured_nodes(run_dir, arxiv_id, evidence.get("hyperparameters") or [], claim_type="result", limit=2)
            or _structured_nodes(run_dir, arxiv_id, evidence.get("results") or [], claim_type="result", limit=2)
        )
    elif section_key == "interpretation":
        nodes = (
            _structured_nodes(run_dir, arxiv_id, evidence.get("complexity") or [], claim_type="result", limit=2)
            or _claim_nodes(run_dir, arxiv_id, claims, {"result"}, limit=2)
        )
    elif section_key == "strengths":
        nodes = _claim_nodes(run_dir, arxiv_id, claims, {"result", "method"}, limit=2)
    elif section_key == "limitations":
        nodes = (
            _structured_nodes(run_dir, arxiv_id, evidence.get("limitations") or [], claim_type="limitation", limit=2)
            or _claim_nodes(run_dir, arxiv_id, claims, {"limitation"}, limit=2)
        )
    elif section_key == "software":
        nodes = (
            _structured_nodes(run_dir, arxiv_id, evidence.get("datasets") or [], claim_type="artifact", limit=2)
            or _structured_nodes(run_dir, arxiv_id, evidence.get("benchmarks") or [], claim_type="artifact", limit=2)
        )
    else:
        nodes = _structured_nodes(run_dir, arxiv_id, evidence.get("neighbors") or [], claim_type="method", limit=2)
    if section_key in METHOD_PACK_REQUIRED_SOURCE_SECTIONS:
        return nodes
    return nodes or _first_available_nodes(run_dir, arxiv_id, evidence, limit=1)


def _build_method_pack(
    run_dir: Path,
    outline: dict[str, Any],
    method: dict[str, Any],
) -> dict[str, Any]:
    methods, families = _outline_method_maps(outline)
    arxiv_id = str(method["arxiv_id"])
    evidence = _read_json_or_empty(run_dir / "10_verified_evidence" / f"{arxiv_id}.json")
    family = families.get(method.get("family_id"), {})
    section_plan = []
    for title in METHOD_PACK_SECTION_TITLES:
        nodes = _section_nodes(run_dir, arxiv_id, evidence, title)
        structured_refs = []
        if title == "Theory":
            structured_refs = [f"equation:{idx}" for idx, _ in enumerate(evidence.get("equations") or [])]
        elif title == "Algorithm":
            structured_refs = [f"algorithm:{idx}" for idx, _ in enumerate(evidence.get("algorithms") or [])]
        section_plan.append(
            {
                "section_title": title,
                "purpose": f"Ground the {title.lower()} section in verified evidence.",
                "source_nodes": nodes,
                "structured_refs": structured_refs,
            }
        )

    neighbors = []
    neighbor_ids = list(method.get("neighbor_method_ids") or [])
    evidence_neighbors = evidence.get("neighbors") or []
    first_source = _first_available_nodes(run_dir, arxiv_id, evidence, limit=1)
    fallback_source_id = first_source[0]["node_id"] if first_source else ""
    for neighbor_id in neighbor_ids:
        neighbor = methods.get(neighbor_id, {})
        source_node_id = fallback_source_id
        relation = "Listed as a neighboring method in the normalized outline."
        for item in evidence_neighbors:
            name = str(item.get("name") or "").lower()
            if neighbor.get("title", "").lower() in name or neighbor_id.replace("-", " ") in name:
                source_node_id = str(item.get("source_node_id") or source_node_id)
                relation = str(item.get("relation") or relation)
                break
        neighbors.append(
            {
                "method_id": neighbor_id,
                "arxiv_id": str(neighbor.get("arxiv_id") or ""),
                "title": str(neighbor.get("title") or neighbor_id),
                "family_id": str(neighbor.get("family_id") or ""),
                "diff_summary": relation,
                "source_node_id": source_node_id,
            }
        )

    structured = {
        field: evidence.get(field) or []
        for field in (
            "equations",
            "algorithms",
            "hyperparameters",
            "complexity",
            "datasets",
            "artifacts",
            "benchmarks",
            "metrics",
            "baselines",
            "results",
            "limitations",
        )
    }
    return {
        "pack_type": "method",
        "method_id": method["id"],
        "method_title": method.get("title", method["id"]),
        "arxiv_id": arxiv_id,
        "family_id": method.get("family_id", ""),
        "family_title": family.get("title", method.get("family_id", "")),
        "known_concepts_assumed": method.get("known_concepts_assumed") or [],
        "knowledge_gaps_to_explain": method.get("knowledge_gaps_to_explain") or [],
        "structured": structured,
        "section_plan": section_plan,
        "neighbors": neighbors,
    }


def _first_text(items: list[dict[str, Any]], key: str, fallback: str) -> str:
    for item in items:
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return fallback


def _build_family_pack(
    run_dir: Path,
    outline: dict[str, Any],
    family: dict[str, Any],
) -> dict[str, Any]:
    methods, families = _outline_method_maps(outline)
    method_entries = []
    comparison_rows = []
    for method_id in family.get("method_ids") or []:
        method = methods.get(method_id)
        if not method:
            continue
        arxiv_id = str(method.get("arxiv_id") or "")
        evidence = _read_json_or_empty(run_dir / "10_verified_evidence" / f"{arxiv_id}.json")
        method_entries.append(
            {"id": method_id, "title": method.get("title", method_id), "arxiv_id": arxiv_id}
        )
        claims = evidence.get("claims") or []
        method_claims = [c for c in claims if str(c.get("claim_type") or "").lower() == "method"]
        result_claims = [c for c in claims if str(c.get("claim_type") or "").lower() == "result"]
        limitation_claims = [c for c in claims if str(c.get("claim_type") or "").lower() == "limitation"]
        source_node_id = (
            str((method_claims or claims or [{}])[0].get("source_node_id") or "")
            if (method_claims or claims)
            else ""
        )
        comparison_rows.append(
            {
                "method_id": method_id,
                "title": method.get("title", method_id),
                "arxiv_id": arxiv_id,
                "mechanism": _first_text(method_claims, "text", f"{method.get('title', method_id)} mechanism."),
                "when_helps": _first_text(result_claims, "text", "Use when the paper's verified results match the task constraints."),
                "when_hurts": _first_text(limitation_claims, "text", "Avoid when the paper's assumptions do not hold."),
                "source_node_id": source_node_id,
            }
        )
    neighbor_entries = [
        {"id": neighbor_id, "title": families.get(neighbor_id, {}).get("title", neighbor_id)}
        for neighbor_id in family.get("neighbor_family_ids") or []
    ]
    data = {
        "method_ids": method_entries,
        "neighbor_family_ids": neighbor_entries,
        "knowledge_gaps_to_explain": family.get("knowledge_gaps_to_explain") or [],
        "known_concepts_assumed": family.get("known_concepts_assumed") or [],
        "comparison_rows": comparison_rows,
    }
    return {
        "pack_type": "family",
        "family_id": family["id"],
        "family_title": family.get("title", family["id"]),
        "community_id": family.get("community_id", ""),
        "topic": outline.get("topic", ""),
        "method_ids": method_entries,
        "neighbor_family_ids": neighbor_entries,
        "knowledge_gaps_to_explain": data["knowledge_gaps_to_explain"],
        "known_concepts_assumed": data["known_concepts_assumed"],
        "comparison_rows": comparison_rows,
        "data": data,
    }


def _build_book_pack(
    run_dir: Path,
    outline: dict[str, Any],
    section: dict[str, Any],
) -> dict[str, Any]:
    known = _read_json_or_empty(run_dir / "06_expansion" / "known_concepts_snapshot.json")
    gaps = _read_json_or_empty(run_dir / "06_expansion" / "knowledge_gap_report.json")
    topic_path = run_dir / "00_input" / "topic.md"
    topic_text = topic_path.read_text() if topic_path.exists() else outline.get("topic", "")
    return {
        "pack_type": "book",
        "section_id": section["id"],
        "section_title": section.get("title", section["id"]),
        "topic": outline.get("topic", ""),
        "data": {
            "topic": outline.get("topic", ""),
            "topic_text": topic_text,
            "known_concepts": known.get("known_concepts") or [],
            "knowledge_gaps": gaps.get("knowledge_gaps") or gaps.get("gaps") or [],
            "families": outline.get("families", []),
            "methods": outline.get("methods", []),
        },
    }


def _normalized_pack_section_title(title: str) -> str:
    return " ".join(str(title).strip().lower().replace("_", " ").split())


def _method_pack_has_required_source_text(path: Path) -> bool:
    try:
        pack = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    sections_with_text = set()
    for section in pack.get("section_plan") or []:
        if not isinstance(section, dict):
            continue
        has_text = any(
            isinstance(source, dict) and str(source.get("section_text") or "").strip()
            for source in section.get("source_nodes") or []
        )
        if has_text:
            sections_with_text.add(_normalized_pack_section_title(section.get("section_title", "")))
    return METHOD_PACK_REQUIRED_SOURCE_SECTIONS.issubset(sections_with_text)


def _method_pack_payload_has_required_source_text(pack: dict[str, Any]) -> bool:
    sections_with_text = set()
    for section in pack.get("section_plan") or []:
        has_text = any(
            isinstance(source, dict) and str(source.get("section_text") or "").strip()
            for source in section.get("source_nodes") or []
        )
        if has_text:
            sections_with_text.add(_normalized_pack_section_title(section.get("section_title", "")))
    return METHOD_PACK_REQUIRED_SOURCE_SECTIONS.issubset(sections_with_text)


def build_deterministic_stage_13_packs(run_dir: Path) -> dict[str, int]:
    outline = load_outline(run_dir)
    methods, families = _outline_method_maps(outline)
    counts = {"book": 0, "families": 0, "methods": 0, "skipped": 0}
    for target in build_chapter_targets(run_dir):
        expected_path = run_dir / _expected_chapter_pack(target)
        if expected_path.exists():
            if target["type"] != "methods" or _method_pack_has_required_source_text(expected_path):
                counts["skipped"] += 1
                continue
        if target["type"] == "methods":
            payload = _build_method_pack(run_dir, outline, methods[target["id"]])
            if not _method_pack_payload_has_required_source_text(payload):
                continue
        elif target["type"] == "families":
            payload = _build_family_pack(run_dir, outline, families[target["id"]])
        else:
            section = next(
                section for section in outline.get("book_sections", []) if section["id"] == target["id"]
            )
            payload = _build_book_pack(run_dir, outline, section)
        _write_json(expected_path, payload)
        counts[target["type"]] += 1
    append_run_log(
        run_dir,
        "13",
        "deterministic",
        (
            f"built book={counts['book']} families={counts['families']} "
            f"methods={counts['methods']} skipped={counts['skipped']}"
        ),
    )
    return counts


def run_stage_13(run_dir: Path) -> None:
    build_deterministic_stage_13_packs(run_dir)
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
        for idx, chunk in enumerate(chunked(targets, 2), start=1)
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


def bootstrap_new_run(
    topic: str,
    phase: str,
    *,
    timeout_seconds: int = BOOTSTRAP_TIMEOUT_SECONDS,
) -> str:
    prompt = "\n".join(
        [
            "Read AGENTS.md first.",
            *DIRECT_SHARD_RULES,
            "Use .agents/skills/auto-research-orchestrator/SKILL.md.",
            f"Run the auto-research pipeline for this topic through Stage 10 only: {topic}",
            "Stop after Stage 10 verified evidence is complete.",
            "Do not run Stage 11 or later.",
            "Print the final run_id on a line exactly like: RUN_ID=<run_id>",
        ]
    )
    try:
        completed = subprocess.run(
            [
                "codex",
                "exec",
                "--cd",
                str(REPO_ROOT),
                "--model",
                "gpt-5.4-mini",
                "-c",
                'approval_policy="never"',
                "--sandbox",
                "workspace-write",
                prompt,
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"bootstrap failed to launch or complete: {error}") from error

    if completed.returncode != 0:
        raise RuntimeError(
            f"bootstrap failed: stderr={completed.stderr}\nstdout={completed.stdout}"
        )
    for line in completed.stdout.splitlines():
        if line.startswith("RUN_ID="):
            run_id = line.split("=", 1)[1].strip()
            _safe_component(run_id, field="run_id")
            return run_id
    raise RuntimeError(
        "bootstrap did not print RUN_ID=<run_id>; "
        f"stdout tail={completed.stdout[-1000:]}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.topic and not args.run_id:
        raise SystemExit("one of --topic or --run-id is required")
    if args.topic and not args.run_id and args.phase == "write":
        raise SystemExit("--topic cannot be used with --phase write; use draft or all")

    run_id = args.run_id
    if run_id is None:
        run_id = bootstrap_new_run(args.topic, args.phase)
    _safe_component(run_id, field="run_id")
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
