from __future__ import annotations

import argparse
import csv
import inspect
import json
import subprocess
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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
DEFAULT_EXECUTOR = "sdk"
DEFAULT_TARGET_SEED_PAPERS = 200
MIN_BOOTSTRAP_PAPER_POOL = 40
DIRECT_SHARD_RULES = [
    "Execute directly in this codex exec session.",
    "Do not spawn subagents, do not run nested codex commands, and do not wait for other agents.",
    "Do not run scripts/run_auto_research.py, python scripts/run_auto_research.py, or python -m scripts.run_auto_research.",
    "Do not import or call bootstrap_new_run.",
    "Do not import or call sdk.codex.",
    "Do not ask for human input.",
]

PRIMARY_ARTIFACTS = {
    "0": ("run_config.json",),
    "1": (
        "00_input/search_plan.json",
        "02_paper_pool/paper_pool.json",
        "02_paper_pool/candidate_pool_report.json",
    ),
    "3": ("05_weak_graph/weak_global_graph.json",),
    "4": ("06_expansion/known_concepts_snapshot.json",),
    "5": (
        "06_expansion/knowledge_gap_report.json",
        "06_expansion/expansion_need_queue.json",
    ),
    "6": ("06_expansion/expansion_round_01.json",),
    "7": (
        "07_scoring/paper_scores.csv",
        "07_scoring/promotion_candidates.csv",
        "07_scoring/promoted_papers.json",
    ),
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

NON_BLOCKING_FORM_ISSUE_CHECKS = {
    "method_word_count_high",
    "family_word_count_high",
}


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


def _load_json(path: Path) -> Any:
    if not path.exists():
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise RuntimeError(f"missing required bootstrap artifact: {display_path}")
    return json.loads(path.read_text())


def _paper_pool_ids(paper_pool: Any) -> list[str]:
    if isinstance(paper_pool, dict):
        return [str(arxiv_id) for arxiv_id in paper_pool.keys()]
    if isinstance(paper_pool, list):
        ids = []
        for item in paper_pool:
            if not isinstance(item, dict) or not item.get("arxiv_id"):
                raise RuntimeError("paper_pool.json list entries must include arxiv_id")
            ids.append(str(item["arxiv_id"]))
        return ids
    raise RuntimeError("paper_pool.json must be a list or object")


def load_paper_pool_arxiv_ids(run_dir: Path) -> list[str]:
    return _paper_pool_ids(_load_json(run_dir / "02_paper_pool" / "paper_pool.json"))


STAGE_7_SCORE_COLUMNS = (
    "arxiv_id",
    "topic_relevance",
    "graph_centrality",
    "citation_or_influence",
    "recency",
    "implementation_impact",
    "chapter_need",
    "knowledge_gap_boost",
    "final_score",
)


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise RuntimeError(f"missing required bootstrap artifact: {display_path}")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"{path.name} must contain at least one row")
    return rows


def _float_score(row: dict[str, str], *, path_name: str) -> float:
    try:
        return float(row.get("final_score", ""))
    except ValueError as error:
        raise RuntimeError(f"{path_name} final_score must be numeric for {row.get('arxiv_id')}") from error


def _seed_pool_kept_count(seed_pool: dict[str, Any]) -> int:
    total_kept = seed_pool.get("total_kept")
    if total_kept is not None:
        try:
            count = int(total_kept)
        except (TypeError, ValueError) as error:
            raise RuntimeError("seed_pool_raw.json total_kept must be an integer") from error
        if count < 0:
            raise RuntimeError("seed_pool_raw.json total_kept must be non-negative")
        return count

    papers = seed_pool.get("papers")
    if isinstance(papers, (dict, list)):
        return len(papers)
    raise RuntimeError("seed_pool_raw.json must include total_kept or papers")


def _bootstrap_target_seed_papers(search_plan: dict[str, Any]) -> int:
    raw_target = search_plan.get("target_seed_papers", DEFAULT_TARGET_SEED_PAPERS)
    try:
        target = int(raw_target)
    except (TypeError, ValueError) as error:
        raise RuntimeError("search_plan.json target_seed_papers must be an integer") from error
    if target < MIN_BOOTSTRAP_PAPER_POOL:
        raise RuntimeError(
            f"search_plan.json target_seed_papers must be at least {MIN_BOOTSTRAP_PAPER_POOL}"
        )
    return target


def _promoted_ids(promoted: Any) -> list[str]:
    if not isinstance(promoted, dict):
        raise RuntimeError("promoted_papers.json must be an object")
    entries = promoted.get("promoted_papers")
    if not isinstance(entries, list):
        raise RuntimeError("promoted_papers.json must contain promoted_papers list")
    ids = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("arxiv_id"):
            raise RuntimeError("promoted_papers entries must include arxiv_id")
        ids.append(str(entry["arxiv_id"]))
    return ids


def validate_stage_7_outputs(
    run_dir: Path,
    *,
    paper_ids: list[str],
    min_promote_score: float = 0.45,
) -> None:
    score_rows = _load_csv_rows(run_dir / "07_scoring" / "paper_scores.csv")
    candidate_rows = _load_csv_rows(run_dir / "07_scoring" / "promotion_candidates.csv")
    expected_ids = set(paper_ids)

    for path_name, rows in (
        ("paper_scores.csv", score_rows),
        ("promotion_candidates.csv", candidate_rows),
    ):
        missing_columns = [column for column in STAGE_7_SCORE_COLUMNS if column not in rows[0]]
        if missing_columns:
            raise RuntimeError(f"{path_name} missing columns: {missing_columns}")
        row_ids = [str(row.get("arxiv_id", "")).strip() for row in rows]
        if any(not arxiv_id for arxiv_id in row_ids):
            raise RuntimeError(f"{path_name} contains a row without arxiv_id")
        if len(row_ids) != len(set(row_ids)):
            raise RuntimeError(f"{path_name} must contain each paper_pool arxiv_id exactly once")
        if len(row_ids) != len(paper_ids) or set(row_ids) != expected_ids:
            raise RuntimeError(
                f"{path_name} must score exactly every paper_pool paper; "
                f"expected {len(expected_ids)}, got {len(set(row_ids))}"
            )

    candidate_scores = [
        _float_score(row, path_name="promotion_candidates.csv") for row in candidate_rows
    ]
    if candidate_scores != sorted(candidate_scores, reverse=True):
        raise RuntimeError("promotion_candidates.csv must be sorted by descending final_score")

    score_by_id = {
        str(row["arxiv_id"]).strip(): _float_score(row, path_name="paper_scores.csv")
        for row in score_rows
    }
    expected_promoted = [
        arxiv_id
        for arxiv_id, score in sorted(score_by_id.items(), key=lambda item: item[1], reverse=True)
        if score >= min_promote_score
    ]
    if not expected_promoted and score_by_id:
        expected_promoted = [max(score_by_id.items(), key=lambda item: item[1])[0]]

    promoted_ids = _promoted_ids(_load_json(run_dir / "07_scoring" / "promoted_papers.json"))
    if promoted_ids != expected_promoted:
        raise RuntimeError(
            "promoted_papers.json must contain exactly every paper above "
            f"min_promote_score={min_promote_score}; expected {expected_promoted}, got {promoted_ids}"
        )


def normalize_stage_7_candidate_csv(run_dir: Path) -> bool:
    """Rewrite promotion_candidates.csv from paper_scores.csv when the ranker emits
    a reduced shortlist schema instead of the full validation-sensitive table.
    """

    score_rows = _load_csv_rows(run_dir / "07_scoring" / "paper_scores.csv")
    candidate_rows = _load_csv_rows(run_dir / "07_scoring" / "promotion_candidates.csv")
    if not score_rows or not candidate_rows:
        return False
    if all(column in candidate_rows[0] for column in STAGE_7_SCORE_COLUMNS):
        return False
    if not all(column in score_rows[0] for column in STAGE_7_SCORE_COLUMNS):
        return False

    normalized_rows = sorted(
        score_rows,
        key=lambda row: _float_score(row, path_name="paper_scores.csv"),
        reverse=True,
    )
    path = run_dir / "07_scoring" / "promotion_candidates.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STAGE_7_SCORE_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {column: row.get(column, "") for column in STAGE_7_SCORE_COLUMNS}
            for row in normalized_rows
        )
    return True


def normalize_stage_7_promoted_json(
    run_dir: Path,
    *,
    min_promote_score: float = 0.45,
) -> bool:
    score_rows = _load_csv_rows(run_dir / "07_scoring" / "paper_scores.csv")
    promoted_path = run_dir / "07_scoring" / "promoted_papers.json"
    promoted_data = _load_json(promoted_path)
    entries = promoted_data.get("promoted_papers") if isinstance(promoted_data, dict) else None
    if not isinstance(entries, list):
        return False

    existing_by_id = {
        str(entry.get("arxiv_id")).strip(): entry
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("arxiv_id", "")).strip()
    }
    sorted_rows = sorted(
        score_rows,
        key=lambda row: _float_score(row, path_name="paper_scores.csv"),
        reverse=True,
    )
    selected_rows = [row for row in sorted_rows if _float_score(row, path_name="paper_scores.csv") >= min_promote_score]
    if not selected_rows and sorted_rows:
        selected_rows = [sorted_rows[0]]

    normalized_entries: list[dict[str, Any]] = []
    for row in selected_rows:
        arxiv_id = str(row.get("arxiv_id", "")).strip()
        payload = dict(existing_by_id.get(arxiv_id, {}))
        payload["arxiv_id"] = arxiv_id
        payload["final_score"] = _float_score(row, path_name="paper_scores.csv")
        normalized_entries.append(payload)

    if entries == normalized_entries:
        return False
    promoted_path.write_text(
        json.dumps({"promoted_papers": normalized_entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def validate_bootstrap_stage_0_10_contract(run_dir: Path) -> None:
    """Fail closed if a bootstrap child skipped real discovery.

    The Stage 0-10 child runs inside a Codex session, so the parent must verify
    the contract from durable artifacts before continuing into outline/chapter
    work. This prevents fixture or hand-written seed pools from being accepted
    as a real research run.
    """
    search_plan = _load_json(run_dir / "00_input" / "search_plan.json")
    aspects = search_plan.get("aspects") if isinstance(search_plan, dict) else None
    if not isinstance(aspects, list) or not (4 <= len(aspects) <= 8):
        raise RuntimeError("Stage 1 search_plan.json must contain 4..8 aspects")
    target_seed_papers = _bootstrap_target_seed_papers(search_plan)
    aspect_ids: list[str] = []
    normal_queries: set[str] = set()
    survey_queries: set[str] = set()
    positive_keywords: set[str] = set()
    for idx, aspect in enumerate(aspects):
        if not isinstance(aspect, dict):
            raise RuntimeError("Stage 1 search_plan aspects must be objects")
        aspect_id = str(aspect.get("aspect_id") or aspect.get("id") or f"aspect_{idx}").strip()
        if not aspect_id:
            raise RuntimeError("Stage 1 search_plan aspects must include non-empty ids")
        aspect_ids.append(aspect_id)
        normal_queries.update(str(q).strip() for q in aspect.get("normal_queries", []) if str(q).strip())
        survey_queries.update(str(q).strip() for q in aspect.get("survey_queries", []) if str(q).strip())
        positive_keywords.update(str(q).strip() for q in aspect.get("positive_keywords", []) if str(q).strip())
    if not normal_queries or not survey_queries or not positive_keywords:
        raise RuntimeError("Stage 1 search_plan must include normal, survey, and positive keyword unions")

    seed_pool = _load_json(run_dir / "01_seed_pool" / "seed_pool_raw.json")
    if not isinstance(seed_pool, dict):
        raise RuntimeError("seed_pool_raw.json must be an object returned by bulk_normal_start_search")
    output_path = seed_pool.get("output_path")
    if not output_path:
        raise RuntimeError("seed_pool_raw.json missing output_path from bulk_normal_start_search")
    raw_path = Path(str(output_path))
    candidate_paths = [raw_path] if raw_path.is_absolute() else [run_dir / raw_path, REPO_ROOT / raw_path]
    resolved_raw_path = next((path.resolve() for path in candidate_paths if path.exists()), None)
    seed_pool_dir = (run_dir / "01_seed_pool").resolve()
    if resolved_raw_path is None or resolved_raw_path.parent != seed_pool_dir:
        raise RuntimeError("bulk_normal_start_search output_path must point inside 01_seed_pool")
    if not resolved_raw_path.name.startswith("bulk_search_results_"):
        raise RuntimeError("Stage 1 must preserve bulk_search_results_<timestamp>.json")
    raw_kept_count = _seed_pool_kept_count(seed_pool)

    paper_pool = _load_json(run_dir / "02_paper_pool" / "paper_pool.json")
    paper_ids = _paper_pool_ids(paper_pool)
    if len(paper_ids) < MIN_BOOTSTRAP_PAPER_POOL:
        raise RuntimeError(
            f"paper_pool.json must contain at least {MIN_BOOTSTRAP_PAPER_POOL} papers, got {len(paper_ids)}"
        )
    required_pool_count = min(target_seed_papers, raw_kept_count)
    if len(paper_ids) < required_pool_count:
        raise RuntimeError(
            f"paper_pool.json must contain at least {required_pool_count} papers when bulk search kept "
            f"{raw_kept_count}; got {len(paper_ids)}"
        )

    candidate_report = _load_json(run_dir / "02_paper_pool" / "candidate_pool_report.json")
    if not isinstance(candidate_report, dict):
        raise RuntimeError("candidate_pool_report.json must be an object")
    if int(candidate_report.get("selected_total", -1)) != len(paper_ids):
        raise RuntimeError("candidate_pool_report.json selected_total must match paper_pool.json")
    if int(candidate_report.get("raw_kept", -1)) != raw_kept_count:
        raise RuntimeError("candidate_pool_report.json raw_kept must match seed_pool_raw.json")
    if int(candidate_report.get("target_seed_papers", -1)) != target_seed_papers:
        raise RuntimeError("candidate_pool_report.json target_seed_papers must match search_plan.json")
    per_aspect_selected = candidate_report.get("per_aspect_selected")
    if not isinstance(per_aspect_selected, dict):
        raise RuntimeError("candidate_pool_report.json must include per_aspect_selected counts")
    covered_aspects = [
        aspect_id
        for aspect_id in aspect_ids
        if int(per_aspect_selected.get(aspect_id, 0) or 0) > 0
    ]
    required_aspect_coverage = min(4, len(aspect_ids))
    if raw_kept_count >= target_seed_papers and len(covered_aspects) < required_aspect_coverage:
        raise RuntimeError(
            "candidate_pool_report.json must show non-zero selection from at least "
            f"{required_aspect_coverage} search aspects when bulk search kept {raw_kept_count}"
        )
    validate_stage_7_outputs(run_dir, paper_ids=paper_ids)

    weak_dir = run_dir / "04_weak_evidence"
    for arxiv_id in paper_ids:
        weak = _load_json(weak_dir / f"{arxiv_id}.json")
        concepts = weak.get("reader_needed_concepts") if isinstance(weak, dict) else None
        if not concepts:
            raise RuntimeError(f"weak evidence for {arxiv_id} has no reader_needed_concepts")

    promoted_ids = _promoted_ids(_load_json(run_dir / "07_scoring" / "promoted_papers.json"))
    if not promoted_ids:
        raise RuntimeError("promoted_papers.json must promote at least one paper")
    for arxiv_id in promoted_ids:
        if not (run_dir / "08_full_markdown" / f"{arxiv_id}.md").exists():
            raise RuntimeError(f"missing full markdown for promoted paper {arxiv_id}")
        if not (run_dir / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json").exists():
            raise RuntimeError(f"missing pageindex tree for promoted paper {arxiv_id}")
        evidence = _load_json(run_dir / "10_verified_evidence" / f"{arxiv_id}.json")
        claims = evidence.get("claims") if isinstance(evidence, dict) else None
        if not claims:
            raise RuntimeError(f"verified evidence for {arxiv_id} has no claims")
        for claim in claims:
            if not claim.get("source_node_id") or not claim.get("source_lines"):
                raise RuntimeError(f"verified claim for {arxiv_id} is missing source grounding")


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
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--executor", choices=("sdk", "cli"), default=DEFAULT_EXECUTOR)
    parser.add_argument("--status", action="store_true")
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
            result = ShardAttemptResult(
                returncode=None,
                stdout="",
                stderr=f"{type(error).__name__}: {error}\n",
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
    if executor not in {"sdk", "cli"}:
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
        recovery_specs = (
            pending if force else [spec for spec in pending if not expected_outputs_exist(run_dir, spec)]
        )
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


def run_stage_11(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
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
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)

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


def merge_weak_graph_fragments(run_dir: Path) -> None:
    fragments_dir = run_dir / "05_weak_graph" / "fragments"
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edge_keys: set[tuple[str, str, str]] = set()
    edges: list[dict[str, Any]] = []
    for path in sorted(fragments_dir.glob("*.json")):
        data = json.loads(path.read_text())
        for node in data.get("nodes", []):
            node_id = str(node.get("id", "")).strip()
            if not node_id:
                raise RuntimeError(f"weak graph node missing id in {path}")
            nodes_by_id.setdefault(node_id, node)
        for edge in data.get("edges", []):
            src = str(edge.get("src") or edge.get("source") or "").strip()
            dst = str(edge.get("dst") or edge.get("target") or "").strip()
            edge_type = str(edge.get("type") or edge.get("relation") or "").strip()
            key = (src, dst, edge_type)
            if not all(key):
                raise RuntimeError(f"weak graph edge missing source/target/relation in {path}")
            if key not in edge_keys:
                edge_keys.add(key)
                edges.append(edge)
    if not nodes_by_id:
        raise RuntimeError("Stage 3 produced no weak graph nodes")
    output = run_dir / "05_weak_graph" / "weak_global_graph.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"nodes": list(nodes_by_id.values()), "edges": edges}, indent=2, sort_keys=True)
        + "\n"
    )


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


def _typed_target_ref(target: dict[str, str]) -> str:
    singular = {"book": "book", "families": "family", "methods": "method"}[target["type"]]
    return f"{singular}:{target['id']}"


def run_stage_12(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
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
    run_shards(run_dir, [spec], max_workers=max_workers, executor=executor)


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


def _chapter_writer_specs(
    run_dir: Path,
    targets: list[dict[str, str]],
    *,
    form_issues_by_id: dict[str, list[dict[str, Any]]] | None = None,
    shard_prefix: str = "write",
) -> list[ShardSpec]:
    specs = []
    agent_by_type = {
        "book": "book_section_writer",
        "families": "family_chapter_writer",
        "methods": "method_chapter_writer",
    }
    id_key_by_type = {
        "book": "section_ids",
        "families": "family_ids",
        "methods": "method_ids",
    }
    for target_type in ("book", "families", "methods"):
        typed_targets = [t for t in targets if t["type"] == target_type]
        shard_size = 1 if target_type == "methods" else 2
        for idx, chunk in enumerate(chunked(typed_targets, shard_size), start=1):
            if not form_issues_by_id and all(
                (run_dir / _expected_chapter_file(t)).exists() for t in chunk
            ):
                continue
            agent = agent_by_type[target_type]
            shard_id = f"{shard_prefix}-{target_type}-{idx:03d}"
            payload: dict[str, Any] = {
                id_key_by_type[target_type]: [target["id"] for target in chunk]
            }
            if form_issues_by_id:
                payload["form_issues"] = {
                    target["id"]: form_issues_by_id.get(target["id"], [])
                    for target in chunk
                }
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
                        payload,
                    ),
                    expected_outputs=[_expected_chapter_file(t) for t in chunk],
                )
            )
    return specs


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
        if not nodes:
            nodes = _claim_nodes(run_dir, arxiv_id, claims, {"method"}, limit=2)
    elif section_key == "algorithm":
        nodes = _structured_nodes(
            run_dir, arxiv_id, evidence.get("algorithms") or [], claim_type="method", limit=3
        )
        if not nodes:
            nodes = _claim_nodes(run_dir, arxiv_id, claims, {"method"}, limit=2)
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


def run_stage_13(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
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
                        {"pack_targets": [_typed_target_ref(target) for target in chunk]},
                    ),
                    expected_outputs=[_expected_chapter_pack(t) for t in chunk],
                )
        for idx, chunk in enumerate(chunked(targets, 2), start=1)
        if any(not (run_dir / _expected_chapter_pack(t)).exists() for t in chunk)
    ]
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)


def run_stage_14(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    targets = build_chapter_targets(run_dir)
    specs = _chapter_writer_specs(run_dir, targets)
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)


def run_stage_15(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    targets = build_chapter_targets(run_dir)
    specs = _verification_specs(run_dir, targets)
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)

    repair_targets, form_issues_by_id = _targets_with_blocking_form_issues(run_dir, targets)
    if repair_targets:
        repair_specs = _chapter_writer_specs(
            run_dir,
            repair_targets,
            form_issues_by_id=form_issues_by_id,
            shard_prefix="rewrite",
        )
        run_shards(
            run_dir,
            repair_specs,
            max_workers=max_workers,
            executor=executor,
            force=True,
        )
        for target in repair_targets:
            (run_dir / _expected_verification_file(target)).unlink(missing_ok=True)
        run_shards(
            run_dir,
            _verification_specs(run_dir, repair_targets, shard_prefix="verify-repair"),
            max_workers=max_workers,
            executor=executor,
        )
        append_run_log(run_dir, "15", "repaired", f"{len(repair_targets)} form issue target(s)")

    _write_verification_summary(run_dir, targets)


def _verification_specs(
    run_dir: Path,
    targets: list[dict[str, str]],
    *,
    shard_prefix: str = "verify",
) -> list[ShardSpec]:
    return [
        ShardSpec(
            stage="15",
            shard_id=f"{shard_prefix}-{idx:03d}",
            agent="verifier",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(
                ".codex/agents/verifier.toml",
                run_dir.name,
                "15",
                f"{shard_prefix}-{idx:03d}",
                {"chapter_targets": [_typed_target_ref(target) for target in chunk]},
            ),
            expected_outputs=[_expected_verification_file(t) for t in chunk],
        )
        for idx, chunk in enumerate(chunked(targets, 2), start=1)
        if any(not (run_dir / _expected_verification_file(t)).exists() for t in chunk)
    ]


def _targets_with_blocking_form_issues(
    run_dir: Path, targets: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, list[dict[str, Any]]]]:
    repair_targets: list[dict[str, str]] = []
    form_issues_by_id: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        verification = _load_verification_or_none(run_dir, target)
        if verification is None:
            continue
        summary = verification.get("summary", {})
        form_issue_count = int(summary.get("form_issue_count") or 0)
        blocking_issues = _blocking_form_issues(verification, form_issue_count)
        if blocking_issues:
            repair_targets.append(target)
            form_issues_by_id[target["id"]] = blocking_issues
    return repair_targets, form_issues_by_id


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
                "passed": _verification_passed(data),
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


def _manifest_chapter_type(target_type: str) -> str:
    return {"book": "book", "families": "family", "methods": "method"}[target_type]


def _outline_entry_for_target(
    outline: dict[str, Any], target: dict[str, str]
) -> dict[str, Any]:
    if target["type"] == "book":
        entries = outline.get("book_sections", [])
    elif target["type"] == "families":
        entries = outline.get("families", [])
    else:
        entries = outline.get("methods", [])
    for entry in entries:
        if entry.get("id") == target["id"]:
            return entry
    return {"id": target["id"], "title": target["id"]}


def _split_markdown_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    return text[: end + len("\n---\n")], text[end + len("\n---\n") :]


def _strip_references_section(body: str) -> str:
    return re.split(r"(?m)^## References\s*$", body, maxsplit=1)[0].rstrip()


def _markdown_word_count(text: str) -> int:
    _, body = _split_markdown_front_matter(text)
    return len(re.findall(r"\b\w+\b", body))


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True)
    return json.dumps(str(value), ensure_ascii=True)


def _write_chapter_front_matter_and_references(
    chapter_path: Path,
    metadata: dict[str, Any],
    references: list[str],
) -> None:
    if not chapter_path.exists():
        return
    _, body = _split_markdown_front_matter(chapter_path.read_text(encoding="utf-8"))
    body = _strip_references_section(body)
    front_matter = "\n".join(
        ["---"]
        + [f"{key}: {_yaml_value(value)}" for key, value in metadata.items()]
        + ["---", ""]
    )
    reference_lines = ["", "## References", ""]
    reference_lines.extend(f"- {reference}" for reference in references)
    chapter_path.write_text(
        front_matter + body.rstrip() + "\n" + "\n".join(reference_lines).rstrip() + "\n",
        encoding="utf-8",
    )


def _verification_passed(verification: dict[str, Any]) -> bool:
    summary = verification.get("summary")
    return verification.get("passed") is True or (
        isinstance(summary, dict) and summary.get("passed") is True
    )


def _verification_status(
    target: dict[str, str],
    verification: dict[str, Any] | None,
    chapter_word_count: int,
) -> tuple[str, str]:
    if verification is None:
        return "excluded_missing_verification", "verification file is missing or unreadable"
    summary = verification.get("summary", {})
    form_issues = int(summary.get("form_issue_count") or 0)
    blocking_form_issues = _blocking_form_issues(verification, form_issues)
    if blocking_form_issues:
        return "excluded_form_issues", f"{len(blocking_form_issues)} form issue(s)"

    word_count = int(summary.get("word_count") or chapter_word_count or 0)
    if target["type"] == "methods" and word_count < 1500:
        return "excluded_too_short", f"method chapter has {word_count} words"
    if target["type"] == "families" and word_count < 1000:
        return "excluded_too_short", f"family chapter has {word_count} words"

    if _verification_passed(verification):
        return "passed", ""
    claims_unsupported = int(summary.get("claims_unsupported") or 0)
    claims_overstated = int(summary.get("claims_overstated") or 0)
    gaps_missing = int(summary.get("gaps_missing") or 0)
    if claims_unsupported or claims_overstated:
        return "excluded_unsupported_claims", "unsupported or overstated claims"
    if gaps_missing:
        return "excluded_missing_evidence", "required evidence gaps missing"
    if _has_only_non_blocking_form_issues(verification, form_issues):
        return "passed", ""
    return "excluded_verification_failed", "verification did not pass"


def _is_non_blocking_form_issue(issue: dict[str, Any]) -> bool:
    check = str(issue.get("check") or "")
    return check in NON_BLOCKING_FORM_ISSUE_CHECKS or check.endswith("_word_count_high")


def _blocking_form_issues(
    verification: dict[str, Any],
    form_issue_count: int,
) -> list[dict[str, Any]]:
    issues = verification.get("form_issues")
    if isinstance(issues, list):
        return [
            issue
            for issue in issues
            if isinstance(issue, dict) and not _is_non_blocking_form_issue(issue)
        ]
    if form_issue_count:
        return [{"check": "unknown_form_issue"}] * form_issue_count
    return []


def _has_only_non_blocking_form_issues(
    verification: dict[str, Any],
    form_issue_count: int,
) -> bool:
    issues = verification.get("form_issues")
    return (
        form_issue_count > 0
        and isinstance(issues, list)
        and any(isinstance(issue, dict) for issue in issues)
        and not _blocking_form_issues(verification, form_issue_count)
    )


def _load_verification_or_none(run_dir: Path, target: dict[str, str]) -> dict[str, Any] | None:
    path = run_dir / _expected_verification_file(target)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _references_for_target(
    target: dict[str, str],
    entry: dict[str, Any],
    method_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    arxiv_ids: list[str] = []
    if target["type"] == "methods" and entry.get("arxiv_id"):
        arxiv_ids.append(str(entry["arxiv_id"]))
    elif target["type"] == "families":
        for method_id in entry.get("method_ids", []) or []:
            method = method_by_id.get(method_id) or {}
            if method.get("arxiv_id"):
                arxiv_ids.append(str(method["arxiv_id"]))
    seen = set()
    references = []
    for arxiv_id in arxiv_ids:
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        references.append(f"[arxiv:{arxiv_id}]")
    return references


def _build_deterministic_chapter_manifest(run_dir: Path) -> dict[str, Any]:
    outline = load_outline(run_dir)
    methods = {method["id"]: method for method in outline.get("methods", [])}
    chapters: list[dict[str, Any]] = []
    for target in build_chapter_targets(run_dir):
        entry = _outline_entry_for_target(outline, target)
        chapter_path = run_dir / _expected_chapter_file(target)
        chapter_text = chapter_path.read_text(encoding="utf-8") if chapter_path.exists() else ""
        chapter_word_count = _markdown_word_count(chapter_text)
        verification = _load_verification_or_none(run_dir, target)
        summary = verification.get("summary", {}) if verification else {}
        word_count = int(summary.get("word_count") or chapter_word_count or 0)
        equations_rendered = int(summary.get("equations_rendered") or chapter_text.count("$$") // 2)
        pseudocode_blocks = int(summary.get("pseudocode_blocks") or chapter_text.count("```") // 2)
        status, reason = _verification_status(target, verification, word_count)

        chapter_type = _manifest_chapter_type(target["type"])
        metadata: dict[str, Any] = {
            "chapter_id": target["id"],
            "chapter_type": chapter_type,
            "title": entry.get("title", target["id"]),
            "status": status,
            "word_count": word_count,
            "equations_rendered": equations_rendered,
            "pseudocode_blocks": pseudocode_blocks,
        }
        if reason:
            metadata["status_reason"] = reason
        if target["type"] == "methods":
            metadata["arxiv_id"] = entry.get("arxiv_id", "")
            metadata["family_id"] = entry.get("family_id", "")
        elif target["type"] == "families":
            metadata["method_ids"] = entry.get("method_ids", []) or []

        references = _references_for_target(target, entry, methods)
        _write_chapter_front_matter_and_references(chapter_path, metadata, references)

        manifest_entry = dict(metadata)
        manifest_entry["file"] = _expected_chapter_file(target)
        chapters.append(manifest_entry)

    return {"run_id": run_dir.name, "generated_at": now_iso(), "chapters": chapters}


def run_stage_16(run_dir: Path, *, max_workers: int = 1) -> None:
    manifest_dir = run_dir / "16_book"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = _build_deterministic_chapter_manifest(run_dir)
    manifest_path = manifest_dir / "chapters_manifest.json"
    tmp_path = manifest_dir / "chapters_manifest.json.tmp"
    tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(manifest_path)
    for shard_path in manifest_dir.glob("chapters_manifest_shard_*.json"):
        shard_path.unlink()
    append_run_log(run_dir, "16", "deterministic", f"{len(manifest['chapters'])} chapters")


def run_stage_16_legacy_sharded(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
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
                    {"chapter_targets": [_typed_target_ref(target) for target in chunk]},
                ),
                expected_outputs=[shard_path],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
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


def run_stage_17(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
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
    run_shards(run_dir, [spec], executor=executor)


def slugify_topic(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:80] or "research"


def start_new_run(topic: str, phase: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{slugify_topic(topic)}-{timestamp}"
    run_id = base
    counter = 2
    while (RUNS_ROOT / run_id).exists():
        run_id = f"{base}-{counter}"
        counter += 1

    run_dir = RUNS_ROOT / run_id
    for rel in (
        "00_input",
        "01_seed_pool",
        "02_paper_pool",
        "03_overviews/semantic_scholar",
        "04_weak_evidence",
        "05_weak_graph/fragments",
        "06_expansion",
        "07_scoring",
        "08_full_markdown",
        "09_pageindex/trees",
        "09_pageindex/nodes",
        "10_verified_evidence",
        "11_verified_graph/fragments",
        "12_taxonomy",
        "13_chapter_packs/book",
        "13_chapter_packs/families",
        "13_chapter_packs/methods",
        "14_chapters/book",
        "14_chapters/families",
        "14_chapters/methods",
        "15_verification/book",
        "15_verification/families",
        "15_verification/methods",
        "16_book",
        "17_learning_suggestions",
    ):
        (run_dir / rel).mkdir(parents=True, exist_ok=True)

    (run_dir / "00_input" / "topic.md").write_text(topic.strip() + "\n")
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "topic": topic,
                "phase": phase,
                "target_seed_papers": DEFAULT_TARGET_SEED_PAPERS,
                "min_promote_score": 0.45,
                "created_at": now_iso(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    append_run_log(run_dir, "0", "completed", "run_config and directories created")
    return run_id


def run_stage_1(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "1"):
        append_run_log(run_dir, "1", "skipped", "paper pool already present")
        return
    topic_path = run_dir / "00_input" / "topic.md"
    topic = topic_path.read_text().strip() if topic_path.exists() else run_dir.name
    spec = ShardSpec(
        stage="1",
        shard_id="seed-pool",
        agent="query_planner",
        model="gpt-5.4",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                *DIRECT_SHARD_RULES,
                "Run Stage 1 only.",
                f"run_id={run_dir.name}",
                f"topic={topic}",
                "Follow .codex/agents/query_planner.toml and .agents/skills/query-planning/SKILL.md.",
                "Write 00_input/search_plan.json.",
                "Call bulk_normal_start_search exactly once with query-planner unions.",
                "Write 01_seed_pool/seed_pool_raw.json and preserve bulk_search_results_<timestamp>.json in 01_seed_pool/.",
                "Build a stratified 02_paper_pool/paper_pool.json and paper_pool.csv.",
                "Write 02_paper_pool/candidate_pool_report.json with raw_kept, target_seed_papers, selected_total, and per_aspect_selected.",
                "Do not run Stage 2 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=[
            "00_input/search_plan.json",
            "01_seed_pool/seed_pool_raw.json",
            "02_paper_pool/paper_pool.json",
            "02_paper_pool/paper_pool.csv",
            "02_paper_pool/candidate_pool_report.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor, timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS)
    paper_pool = _load_json(run_dir / "02_paper_pool" / "paper_pool.json")
    paper_ids = _paper_pool_ids(paper_pool)
    if len(paper_ids) < MIN_BOOTSTRAP_PAPER_POOL:
        raise RuntimeError(f"Stage 1 produced too few papers: {len(paper_ids)}")
    append_run_log(run_dir, "1", "completed", f"paper pool contains {len(paper_ids)} papers")


def run_stage_2(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "04_weak_evidence" / f"{arxiv_id}.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 5), start=1):
        shard_id = f"weak-evidence-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="2",
                shard_id=shard_id,
                agent="weak_evidence_extractor",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/weak_evidence_extractor.toml",
                    run_dir.name,
                    "2",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[f"04_weak_evidence/{arxiv_id}.json" for arxiv_id in chunk],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    still_missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "04_weak_evidence" / f"{arxiv_id}.json").exists()
    ]
    if still_missing:
        raise RuntimeError(f"Stage 2 missing weak evidence: {still_missing[:10]}")
    append_run_log(
        run_dir, "2", "completed", f"weak evidence generated for {len(paper_ids)} papers"
    )


def run_stage_3(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "3"):
        append_run_log(run_dir, "3", "skipped", "weak graph already present")
        return
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "05_weak_graph" / "fragments" / f"{arxiv_id}.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 5), start=1):
        shard_id = f"weak-graph-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="3",
                shard_id=shard_id,
                agent="weak_graph_extractor",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/weak_graph_extractor.toml",
                    run_dir.name,
                    "3",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[
                    f"05_weak_graph/fragments/{arxiv_id}.json" for arxiv_id in chunk
                ],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    merge_weak_graph_fragments(run_dir)
    append_run_log(run_dir, "3", "completed", "weak graph merged")


def run_stage_4(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "4"):
        append_run_log(run_dir, "4", "skipped", "knowledge base snapshot already present")
        return
    spec = ShardSpec(
        stage="4",
        shard_id="knowledge-base",
        agent="knowledge_base_reader",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_base_reader.toml",
            run_dir.name,
            "4",
            "knowledge-base",
            {},
        ),
        expected_outputs=["06_expansion/known_concepts_snapshot.json"],
    )
    run_shards(run_dir, [spec], executor=executor)
    append_run_log(run_dir, "4", "completed", "knowledge base snapshot written")


def run_stage_5(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "5"):
        append_run_log(run_dir, "5", "skipped", "knowledge gap report already present")
        return
    spec = ShardSpec(
        stage="5",
        shard_id="knowledge-gaps",
        agent="knowledge_gap_detector",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_gap_detector.toml",
            run_dir.name,
            "5",
            "knowledge-gaps",
            {},
        ),
        expected_outputs=[
            "06_expansion/knowledge_gap_report.json",
            "06_expansion/expansion_need_queue.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor)
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    append_run_log(
        run_dir, "5", "completed", f"knowledge gap report written; queue_items={len(items)}"
    )


def load_expansion_gap_items(run_dir: Path) -> list[dict[str, Any]]:
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    if not isinstance(items, list):
        raise RuntimeError("expansion_need_queue.json items must be a list")
    return [item for item in items if isinstance(item, dict)]


def _first_existing_path(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def merge_expansion_shards(run_dir: Path, shard_ids: list[str]) -> None:
    expansion_dir = run_dir / "06_expansion"
    shards_dir = expansion_dir / "shards"
    accepted_rows: list[str] = []
    rejected_rows: list[str] = []
    round_items: list[dict[str, Any]] = []
    accepted_header = "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
    rejected_header = "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
    for shard_id in shard_ids:
        round_path = _first_existing_path(
            [
                shards_dir / f"{shard_id}_round.json",
                expansion_dir / f"expansion_round_01_shard_{shard_id}.json",
            ]
        )
        if round_path:
            data = json.loads(round_path.read_text())
            if isinstance(data, dict):
                round_items.extend(data.get("items", []) or [])
        for paths, rows in (
            (
                [
                    shards_dir / f"{shard_id}_accepted_candidates.csv",
                    expansion_dir / f"accepted_candidates_shard_{shard_id}.csv",
                ],
                accepted_rows,
            ),
            (
                [
                    shards_dir / f"{shard_id}_rejected_candidates.csv",
                    expansion_dir / f"rejected_candidates_shard_{shard_id}.csv",
                ],
                rejected_rows,
            ),
        ):
            path = _first_existing_path(paths)
            if path:
                lines = path.read_text().splitlines()
                rows.extend(line for line in lines[1:] if line.strip())
    (expansion_dir / "accepted_candidates.csv").write_text(
        accepted_header + "\n".join(accepted_rows) + ("\n" if accepted_rows else "")
    )
    (expansion_dir / "rejected_candidates.csv").write_text(
        rejected_header + "\n".join(rejected_rows) + ("\n" if rejected_rows else "")
    )
    (expansion_dir / "expansion_round_01.json").write_text(
        json.dumps(
            {"status": "completed" if round_items else "skipped", "items": round_items},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def run_stage_6(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "6"):
        append_run_log(run_dir, "6", "skipped", "expansion round already present")
        return
    gap_items = load_expansion_gap_items(run_dir)
    expansion_dir = run_dir / "06_expansion"
    expansion_dir.mkdir(parents=True, exist_ok=True)
    if not gap_items:
        (expansion_dir / "expansion_round_01.json").write_text(
            json.dumps({"status": "skipped", "items": []}, indent=2, sort_keys=True) + "\n"
        )
        (expansion_dir / "accepted_candidates.csv").write_text(
            "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed\n"
        )
        (expansion_dir / "rejected_candidates.csv").write_text(
            "arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_rejected\n"
        )
        append_run_log(run_dir, "6", "skipped", "no expansion gaps")
        return
    shard_ids = []
    specs = []
    for idx, item in enumerate(gap_items, start=1):
        shard_id = f"expansion-{idx:03d}"
        shard_ids.append(shard_id)
        specs.append(
            ShardSpec(
                stage="6",
                shard_id=shard_id,
                agent="paper_expander",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/paper_expander.toml",
                    run_dir.name,
                    "6",
                    shard_id,
                    {"gap_items": [item]},
                ),
                expected_outputs=[
                    f"06_expansion/expansion_round_01_shard_{shard_id}.json",
                    f"06_expansion/accepted_candidates_shard_{shard_id}.csv",
                    f"06_expansion/rejected_candidates_shard_{shard_id}.csv",
                ],
            )
        )
    run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    merge_expansion_shards(run_dir, shard_ids)
    append_run_log(run_dir, "6", "completed", f"expanded {len(gap_items)} gaps")


def run_stage_7(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    if primary_artifact_exists(run_dir, "7"):
        if normalize_stage_7_candidate_csv(run_dir):
            append_run_log(run_dir, "7", "normalized", "promotion_candidates.csv rebuilt from paper_scores.csv")
        if normalize_stage_7_promoted_json(run_dir):
            append_run_log(run_dir, "7", "normalized", "promoted_papers.json rebuilt from paper_scores.csv")
        validate_stage_7_outputs(run_dir, paper_ids=paper_ids)
        append_run_log(run_dir, "7", "skipped", "scoring artifacts already present")
        return
    spec = ShardSpec(
        stage="7",
        shard_id="paper-ranker",
        agent="paper_ranker",
        model="gpt-5.4-mini",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                *DIRECT_SHARD_RULES,
                "Run Stage 7 scoring only.",
                f"run_id={run_dir.name}",
                "Follow .codex/agents/paper_ranker.toml exactly.",
                "Read 02_paper_pool/paper_pool.json, 04_weak_evidence/*.json, 05_weak_graph/weak_global_graph.json, and 06_expansion/knowledge_gap_report.json.",
                "Write all three outputs: 07_scoring/paper_scores.csv, 07_scoring/promotion_candidates.csv, 07_scoring/promoted_papers.json.",
                "Do not fetch markdown.",
                "Do not run Stage 8 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=[
            "07_scoring/paper_scores.csv",
            "07_scoring/promotion_candidates.csv",
            "07_scoring/promoted_papers.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor)
    if normalize_stage_7_candidate_csv(run_dir):
        append_run_log(run_dir, "7", "normalized", "promotion_candidates.csv rebuilt from paper_scores.csv")
    if normalize_stage_7_promoted_json(run_dir):
        append_run_log(run_dir, "7", "normalized", "promoted_papers.json rebuilt from paper_scores.csv")
    validate_stage_7_outputs(run_dir, paper_ids=paper_ids)
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    append_run_log(run_dir, "7", "completed", f"{len(paper_ids)} scored, {len(promoted_ids)} promoted")


def run_stage_8(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not (run_dir / "08_full_markdown" / f"{arxiv_id}.md").exists()
    ]
    if not missing:
        append_run_log(run_dir, "8", "skipped", "markdown already present")
        return
    spec = ShardSpec(
        stage="8",
        shard_id="full-markdown",
        agent="knowledge_base_reader",
        model="gpt-5.4-mini",
        prompt="\n".join(
            [
                "Read AGENTS.md first.",
                *DIRECT_SHARD_RULES,
                "Run Stage 8 full markdown fetch only.",
                f"run_id={run_dir.name}",
                f"arxiv_ids={missing}",
                "For each arxiv_id, call get_paper_markdown and write 08_full_markdown/{arxiv_id}.md.",
                "Do not run Stage 9 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=[f"08_full_markdown/{arxiv_id}.md" for arxiv_id in missing],
    )
    run_shards(run_dir, [spec], executor=executor, timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS)
    append_run_log(run_dir, "8", "completed", f"markdown fetched for {len(missing)} papers")


def run_stage_9(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not (run_dir / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json").exists()
        or not (run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 2), start=1):
        shard_id = f"pageindex-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="9",
                shard_id=shard_id,
                agent="paper_indexer",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/paper_indexer.toml",
                    run_dir.name,
                    "9",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[
                    output
                    for arxiv_id in chunk
                    for output in (
                        f"09_pageindex/trees/{arxiv_id}.tree.json",
                        f"09_pageindex/nodes/{arxiv_id}.nodes.json",
                    )
                ],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    append_run_log(run_dir, "9", "completed", f"page indexes ready for {len(promoted_ids)} papers")


def run_stage_10(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    promoted_ids = load_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not (run_dir / "10_verified_evidence" / f"{arxiv_id}.json").exists()
    ]
    specs = []
    for idx, chunk in enumerate(chunked(missing, 1), start=1):
        shard_id = f"verified-evidence-{idx:03d}"
        specs.append(
            ShardSpec(
                stage="10",
                shard_id=shard_id,
                agent="verified_evidence_extractor",
                model="gpt-5.4-mini",
                prompt=_generic_agent_prompt(
                    ".codex/agents/verified_evidence_extractor.toml",
                    run_dir.name,
                    "10",
                    shard_id,
                    {"arxiv_ids": chunk},
                ),
                expected_outputs=[f"10_verified_evidence/{arxiv_id}.json" for arxiv_id in chunk],
            )
        )
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    for arxiv_id in promoted_ids:
        evidence = _load_json(run_dir / "10_verified_evidence" / f"{arxiv_id}.json")
        claims = evidence.get("claims") if isinstance(evidence, dict) else None
        if not claims:
            raise RuntimeError(f"verified evidence for {arxiv_id} has no claims")
        for claim in claims:
            if not claim.get("source_node_id") or not claim.get("source_lines"):
                raise RuntimeError(f"verified claim for {arxiv_id} is missing source grounding")
    append_run_log(
        run_dir, "10", "completed", f"verified evidence ready for {len(promoted_ids)} papers"
    )


def bootstrap_new_run(
    topic: str,
    phase: str,
    *,
    timeout_seconds: int = BOOTSTRAP_TIMEOUT_SECONDS,
    executor: str = DEFAULT_EXECUTOR,
) -> str:
    raise RuntimeError(
        "bootstrap_new_run is retired; use start_new_run plus stage-scoped handlers"
    )


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
    )


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


def _latest_shard_manifest(run_dir: Path) -> dict[str, Any] | None:
    manifests = [
        path
        for path in (run_dir / "run_control" / "stages").glob("*/*/*.json")
        if path.parent.name == "shards"
    ]
    if not manifests:
        return None
    failed = []
    for path in manifests:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        data["_manifest_path"] = str(path.relative_to(run_dir))
        if data.get("status") == "failed":
            failed.append((path.stat().st_mtime, data))
    if failed:
        return max(failed, key=lambda item: item[0])[1]
    latest_path = max(manifests, key=lambda path: path.stat().st_mtime)
    try:
        data = json.loads(latest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    data["_manifest_path"] = str(latest_path.relative_to(run_dir))
    return data


def format_run_status(run_dir: Path) -> str:
    state = load_run_state(run_dir)
    shard = _latest_shard_manifest(run_dir)
    lines = [
        f"run_id={run_dir.name}",
        f"status={state.get('status', 'unknown')}",
        f"current_stage={state.get('current_stage', '')}",
        f"last_completed_stage={state.get('last_completed_stage', '')}",
    ]
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
        _run_stage_handler(
            handler,
            run_dir,
            max_workers=args.max_workers,
            executor=args.executor,
        )
        save_run_state(
            run_dir,
            {**load_run_state(run_dir), "last_completed_stage": stage},
        )

    save_run_state(run_dir, {**load_run_state(run_dir), "status": "completed"})
    print(f"{args.phase} phase complete. run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
