from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import inspect
import json
import os
import requests
import signal
import subprocess
import sys
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Iterable
from urllib.parse import quote

from swarn_research_mcp.research_book import BOOK_FILE_BY_ID
from knowledge_gap_aggregator import build_digest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "research_runs"
AUTO_RESEARCH_BULK_SEARCH_CONFIG = REPO_ROOT / "swarn_research_mcp" / "bulk_search_config.json"
ARXIV2MD_MARKDOWN_URL = "https://arxiv2md.org/api/markdown"
STAGE_8_MARKDOWN_FETCH_TIMEOUT_SECONDS = 45
DEFAULT_SHARD_TIMEOUT_SECONDS = 3 * 3600
BOOTSTRAP_TIMEOUT_SECONDS = 6 * 3600
DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS = 15 * 60
DEFAULT_EXECUTOR = "sdk-cli-fallback"
DEFAULT_MAX_EFFECTIVE_WORKERS = 20
DEFAULT_STAGE_MAX_EFFECTIVE_WORKERS = {
    "2": 20,
    "3": 20,
    "6": 10,
    "8": 20,
    "9": 20,
    "10": 5,
    "11": 10,
    "13": 5,
    "14": 10,
    "15": 5,
    "16": 20,
    "17": 20,
    "18": 20,
}
DEFAULT_STAGE_6_CODEX_RELEVANCE_SESSION_LIMIT = 1
MIN_BOOTSTRAP_PAPER_POOL = 40
STAGE_1_MAX_NORMAL_QUERIES = 5
STAGE_1_MAX_SURVEY_QUERIES = 3
STAGE_1_MIN_ASPECTS = 4
STAGE_1_MAX_ASPECTS = 5
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
        "01_seed_pool/seed_pool_raw.json",
        "02_paper_pool/paper_pool.json",
        "02_paper_pool/paper_pool.csv",
        "02_paper_pool/candidate_pool_report.json",
    ),
    "3": ("05_weak_graph/weak_global_graph.json",),
    "4": ("06_expansion/known_concepts_snapshot.json",),
    "5": (
        "06_expansion/gap_candidates_digest.json",
        "06_expansion/extracted_concepts.json",
        "06_expansion/knowledge_gap_report.json",
        "06_expansion/expansion_need_queue.json",
        "06_expansion/stage5_metadata.json",
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

_RUN_LOG_LOCK = threading.Lock()


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


def load_paper_pool_records(run_dir: Path) -> list[dict[str, Any]]:
    paper_pool = _load_json(run_dir / "02_paper_pool" / "paper_pool.json")
    if isinstance(paper_pool, dict):
        records = []
        for arxiv_id, value in paper_pool.items():
            if isinstance(value, dict):
                record = dict(value)
                record.setdefault("arxiv_id", str(arxiv_id))
            else:
                record = {"arxiv_id": str(arxiv_id), "abstract": value}
            records.append(record)
        return records
    if isinstance(paper_pool, list):
        records = []
        for item in paper_pool:
            if not isinstance(item, dict) or not item.get("arxiv_id"):
                raise RuntimeError("paper_pool.json list entries must include arxiv_id")
            records.append(dict(item))
        return records
    raise RuntimeError("paper_pool.json must be a list or object")


def write_paper_pool_records(run_dir: Path, records: list[dict[str, Any]]) -> None:
    _write_json(run_dir / "02_paper_pool" / "paper_pool.json", records)
    csv_path = run_dir / "02_paper_pool" / "paper_pool.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arxiv_id"])
        writer.writeheader()
        for record in records:
            writer.writerow({"arxiv_id": str(record["arxiv_id"])})


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


def _kept_paper_ids(papers: Any, *, path_name: str) -> list[str]:
    if isinstance(papers, dict) and isinstance(papers.get("papers"), (dict, list)):
        return _kept_paper_ids(papers["papers"], path_name=f"{path_name} papers")
    if isinstance(papers, dict):
        return [str(arxiv_id) for arxiv_id in papers.keys()]
    if isinstance(papers, list):
        ids: list[str] = []
        for item in papers:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and item.get("arxiv_id"):
                ids.append(str(item["arxiv_id"]))
            else:
                raise RuntimeError(f"{path_name} list entries must be strings or include arxiv_id")
        return ids
    raise RuntimeError(f"{path_name} must be an object or list")


def _seed_pool_ids(seed_pool: dict[str, Any]) -> list[str]:
    papers = seed_pool.get("papers")
    if not isinstance(papers, (dict, list)):
        raise RuntimeError("seed_pool_raw.json must include papers as an object or list")
    return _kept_paper_ids(papers, path_name="seed_pool_raw.json papers")


def _duplicate_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for arxiv_id in ids:
        if arxiv_id in seen:
            duplicates.add(arxiv_id)
        seen.add(arxiv_id)
    return sorted(duplicates)


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


def _promoted_ids_readonly(promoted: Any) -> list[str]:
    if isinstance(promoted, dict):
        return _promoted_ids(promoted)
    if isinstance(promoted, list):
        ids: list[str] = []
        for entry in promoted:
            if isinstance(entry, str):
                ids.append(entry)
            elif isinstance(entry, dict) and entry.get("arxiv_id"):
                ids.append(str(entry["arxiv_id"]))
            else:
                raise RuntimeError("promoted_papers list entries must be strings or include arxiv_id")
        return ids
    raise RuntimeError("promoted_papers.json must be an object or legacy list")


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
    if isinstance(promoted_data, list):
        entries = promoted_data
    else:
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

    if isinstance(promoted_data, dict) and entries == normalized_entries:
        return False
    promoted_path.write_text(
        json.dumps({"promoted_papers": normalized_entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def validate_stage_1_search_plan(
    run_dir: Path,
    *,
    enforce_query_budget: bool = False,
) -> None:
    search_plan = _load_json(run_dir / "00_input" / "search_plan.json")
    aspects = search_plan.get("aspects") if isinstance(search_plan, dict) else None
    if not isinstance(aspects, list) or not (STAGE_1_MIN_ASPECTS <= len(aspects) <= STAGE_1_MAX_ASPECTS):
        raise RuntimeError(
            f"Stage 1 search_plan.json must contain {STAGE_1_MIN_ASPECTS}..{STAGE_1_MAX_ASPECTS} aspects"
        )
    normal_query_count = 0
    survey_query_count = 0
    for idx, aspect in enumerate(aspects):
        if not isinstance(aspect, dict):
            raise RuntimeError("Stage 1 search_plan aspects must be objects")
        aspect_id = str(aspect.get("aspect_id") or aspect.get("id") or "").strip()
        if not aspect_id:
            raise RuntimeError("Stage 1 search_plan aspects must include non-empty ids")
        for field in ("normal_queries", "positive_keywords"):
            values = aspect.get(field)
            if not isinstance(values, list) or not any(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise RuntimeError(
                    f"Stage 1 search_plan aspect {aspect_id} must include non-empty "
                    "normal_queries and positive_keywords"
                )
        survey_values = aspect.get("survey_queries")
        if not isinstance(survey_values, list):
            raise RuntimeError(
                f"Stage 1 search_plan aspect {aspect_id} must include survey_queries list"
            )
        normal_query_count += len(_dedupe_str_list(aspect.get("normal_queries") or []))
        survey_query_count += len(_dedupe_str_list(survey_values))
    if enforce_query_budget and normal_query_count > STAGE_1_MAX_NORMAL_QUERIES:
        raise RuntimeError(
            f"Stage 1 search_plan normal query count must be <= {STAGE_1_MAX_NORMAL_QUERIES}"
        )
    if enforce_query_budget and survey_query_count > STAGE_1_MAX_SURVEY_QUERIES:
        raise RuntimeError(
            f"Stage 1 search_plan survey query count must be <= {STAGE_1_MAX_SURVEY_QUERIES}"
        )


def validate_stage_1_keep_all_contract(
    run_dir: Path,
    *,
    enforce_query_budget: bool = False,
) -> list[str]:
    validate_stage_1_search_plan(run_dir, enforce_query_budget=enforce_query_budget)

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
    bulk_search_results = _load_json(resolved_raw_path)
    raw_kept_count = _seed_pool_kept_count(seed_pool)
    raw_seed_ids = _seed_pool_ids(seed_pool)
    if len(raw_seed_ids) != raw_kept_count:
        raise RuntimeError(
            "seed_pool_raw.json total_kept must match the number of papers in papers"
        )
    raw_duplicates = _duplicate_ids(raw_seed_ids)
    if raw_duplicates:
        raise RuntimeError(
            f"seed_pool_raw.json papers must not contain duplicate arxiv_id values: {raw_duplicates[:10]}"
        )
    bulk_ids = _kept_paper_ids(bulk_search_results, path_name=resolved_raw_path.name)
    if set(bulk_ids) != set(raw_seed_ids):
        missing = sorted(set(raw_seed_ids) - set(bulk_ids))
        extra = sorted(set(bulk_ids) - set(raw_seed_ids))
        raise RuntimeError(
            "bulk_search_results artifact must match seed_pool_raw.json papers; "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )

    paper_pool = _load_json(run_dir / "02_paper_pool" / "paper_pool.json")
    paper_ids = _paper_pool_ids(paper_pool)
    paper_duplicates = _duplicate_ids(paper_ids)
    if paper_duplicates:
        raise RuntimeError(
            f"paper_pool.json must not contain duplicate arxiv_id values: {paper_duplicates[:10]}"
        )
    if len(paper_ids) < MIN_BOOTSTRAP_PAPER_POOL:
        raise RuntimeError(
            f"paper_pool.json must contain at least {MIN_BOOTSTRAP_PAPER_POOL} papers, got {len(paper_ids)}"
        )
    if set(paper_ids) != set(raw_seed_ids):
        missing = sorted(set(raw_seed_ids) - set(paper_ids))
        extra = sorted(set(paper_ids) - set(raw_seed_ids))
        raise RuntimeError(
            "paper_pool.json must contain every paper kept by bulk search; "
            f"missing={missing[:10]}, extra={extra[:10]}, "
            f"raw_kept={len(raw_seed_ids)}, selected={len(paper_ids)}"
        )

    candidate_report = _load_json(run_dir / "02_paper_pool" / "candidate_pool_report.json")
    if not isinstance(candidate_report, dict):
        raise RuntimeError("candidate_pool_report.json must be an object")
    if int(candidate_report.get("selected_total", -1)) != raw_kept_count:
        raise RuntimeError("candidate_pool_report.json selected_total must match seed_pool_raw.json")
    if int(candidate_report.get("raw_kept", -1)) != raw_kept_count:
        raise RuntimeError("candidate_pool_report.json raw_kept must match seed_pool_raw.json")
    per_aspect_selected = candidate_report.get("per_aspect_selected")
    if per_aspect_selected is not None and not isinstance(per_aspect_selected, dict):
        raise RuntimeError("candidate_pool_report.json per_aspect_selected must be an object when present")
    selection_policy = candidate_report.get("selection_policy")
    if selection_policy is not None and selection_policy != "keep_all_bulk_search_results":
        raise RuntimeError("candidate_pool_report.json selection_policy must be keep_all_bulk_search_results")

    csv_path = run_dir / "02_paper_pool" / "paper_pool.csv"
    if not csv_path.exists():
        try:
            display_path = csv_path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = csv_path
        raise RuntimeError(f"missing required bootstrap artifact: {display_path}")
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "arxiv_id" not in reader.fieldnames:
            raise RuntimeError("paper_pool.csv must include arxiv_id column")
        csv_ids = [str(row.get("arxiv_id", "")).strip() for row in reader]
    csv_duplicates = _duplicate_ids(csv_ids)
    if csv_duplicates:
        raise RuntimeError(
            f"paper_pool.csv must not contain duplicate arxiv_id values: {csv_duplicates[:10]}"
        )
    if set(csv_ids) != set(paper_ids):
        missing = sorted(set(paper_ids) - set(csv_ids))
        extra = sorted(set(csv_ids) - set(paper_ids))
        raise RuntimeError(
            "paper_pool.csv must contain exactly every paper_pool arxiv_id; "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )

    return paper_ids


def _dedupe_str_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _build_stage_1_search_inputs(search_plan: dict[str, Any]) -> tuple[list[str], list[str], list[str], list[str]]:
    aspects = search_plan.get("aspects")
    if not isinstance(aspects, list):
        raise RuntimeError("Stage 1 search_plan.json must contain aspects list")
    queries: list[Any] = []
    survey_queries: list[Any] = []
    positive_keywords: list[Any] = []
    negative_keywords: list[Any] = []
    for aspect in aspects:
        if not isinstance(aspect, dict):
            raise RuntimeError("Stage 1 search_plan aspects must be objects")
        normal_query = _dedupe_str_list(aspect.get("normal_queries") or [])[:1]
        survey_query = _dedupe_str_list(aspect.get("survey_queries") or [])[:1]
        queries.extend(normal_query)
        survey_queries.extend(survey_query)
        positive_keywords.extend(aspect.get("positive_keywords") or [])
        negative_keywords.extend(aspect.get("negative_keywords") or [])
    negative_keywords.extend(search_plan.get("global_negative_keywords") or [])
    return (
        _dedupe_str_list(queries)[:STAGE_1_MAX_NORMAL_QUERIES],
        _dedupe_str_list(survey_queries)[:STAGE_1_MAX_SURVEY_QUERIES],
        _dedupe_str_list(positive_keywords),
        _dedupe_str_list(negative_keywords),
    )


def _paper_pool_records(seed_papers: Any) -> list[dict[str, Any]]:
    if isinstance(seed_papers, dict):
        return [
            {"arxiv_id": str(arxiv_id), "abstract": abstract}
            for arxiv_id, abstract in seed_papers.items()
        ]
    if not isinstance(seed_papers, list):
        raise RuntimeError("seed_pool_raw.json papers must be an object or list")
    records: list[dict[str, Any]] = []
    for item in seed_papers:
        if isinstance(item, str):
            records.append({"arxiv_id": item})
            continue
        if isinstance(item, dict) and item.get("arxiv_id"):
            records.append(dict(item))
            continue
        raise RuntimeError("seed_pool_raw.json papers list entries must be strings or include arxiv_id")
    return records


def _materialize_stage_1_seed_pool(run_dir: Path) -> None:
    from swarn_research_mcp.tools.paper_search import bulk_normal_start_search

    search_plan = _load_json(run_dir / "00_input" / "search_plan.json")
    if not isinstance(search_plan, dict):
        raise RuntimeError("Stage 1 search_plan.json must be an object")
    queries, survey_queries, positive_keywords, negative_keywords = _build_stage_1_search_inputs(search_plan)
    seed_pool_dir = run_dir / "01_seed_pool"
    seed_pool_dir.mkdir(parents=True, exist_ok=True)
    config_was_unset = "SWARN_BULK_SEARCH_CONFIG" not in os.environ
    if config_was_unset:
        os.environ["SWARN_BULK_SEARCH_CONFIG"] = str(AUTO_RESEARCH_BULK_SEARCH_CONFIG)
    append_run_log(
        run_dir,
        "1",
        "materializing",
        (
            f"bulk search config={os.environ['SWARN_BULK_SEARCH_CONFIG']}; "
            f"normal_queries={len(queries)} survey_queries={len(survey_queries)}"
        ),
    )
    try:
        result = asyncio.run(
            bulk_normal_start_search(
                queries=queries,
                survey_queries=survey_queries,
                positive_keywords=positive_keywords,
                negative_keywords=negative_keywords,
                output_dir=str(seed_pool_dir),
            )
        )
    finally:
        if config_was_unset:
            os.environ.pop("SWARN_BULK_SEARCH_CONFIG", None)
    if not isinstance(result, dict) or not isinstance(result.get("papers"), (dict, list)):
        raise RuntimeError("bulk_normal_start_search must return a result object with papers")
    _write_json(seed_pool_dir / "seed_pool_raw.json", result)

    paper_records = _paper_pool_records(result["papers"])
    _write_json(run_dir / "02_paper_pool" / "paper_pool.json", paper_records)

    csv_path = run_dir / "02_paper_pool" / "paper_pool.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arxiv_id"])
        writer.writeheader()
        for record in paper_records:
            writer.writerow({"arxiv_id": str(record["arxiv_id"])})

    _write_json(
        run_dir / "02_paper_pool" / "candidate_pool_report.json",
        {
            "raw_kept": len(paper_records),
            "selected_total": len(paper_records),
            "selection_policy": "keep_all_bulk_search_results",
            "per_aspect_selected": {},
        },
    )


def validate_bootstrap_stage_0_10_contract(run_dir: Path) -> None:
    """Fail closed if a bootstrap child skipped real discovery.

    The Stage 0-10 child runs inside a Codex session, so the parent must verify
    the contract from durable artifacts before continuing into outline/chapter
    work. This prevents fixture or hand-written seed pools from being accepted
    as a real research run.
    """
    paper_ids = validate_stage_1_keep_all_contract(run_dir)
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
    unavailable_ids = _stage_8_unavailable_ids(run_dir)
    for arxiv_id in promoted_ids:
        if not _markdown_is_usable(run_dir / "08_full_markdown" / f"{arxiv_id}.md"):
            if arxiv_id in unavailable_ids:
                continue
            raise RuntimeError(f"missing full markdown for promoted paper {arxiv_id}")
        if not _pageindex_artifacts_valid(run_dir, arxiv_id):
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


def _stable_stage_8_shard_id(arxiv_id: str) -> str:
    stem = quote(str(arxiv_id), safe="").replace("%", "pct")
    return f"full-markdown-{stem}"


def _fetch_arxiv_markdown_sync(arxiv_id: str) -> str:
    response = requests.get(
        ARXIV2MD_MARKDOWN_URL,
        params={"url": arxiv_id, "remove_toc": "false"},
        timeout=STAGE_8_MARKDOWN_FETCH_TIMEOUT_SECONDS,
    )
    if response.status_code in {400, 404, 410, 422}:
        raise Stage8MarkdownUnavailable(f"HTTP {response.status_code} from arxiv2md for {arxiv_id}")
    response.raise_for_status()
    return response.text


def _record_stage_8_unavailable_markdown(
    run_dir: Path,
    unavailable: list[tuple[str, BaseException]],
) -> None:
    path = run_dir / "08_full_markdown" / "unavailable_markdown.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                arxiv_id = row.get("arxiv_id")
                if arxiv_id:
                    existing[arxiv_id] = row
    for arxiv_id, error in unavailable:
        existing[arxiv_id] = {
            "arxiv_id": arxiv_id,
            "error_type": type(error).__name__,
            "error": str(error),
        }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arxiv_id", "error_type", "error"])
        writer.writeheader()
        for arxiv_id in sorted(existing):
            writer.writerow(existing[arxiv_id])


def _clear_stage_8_unavailable_markdown(run_dir: Path, arxiv_ids: list[str]) -> None:
    path = run_dir / "08_full_markdown" / "unavailable_markdown.csv"
    if not path.exists() or not arxiv_ids:
        return
    cleared = set(arxiv_ids)
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            arxiv_id = row.get("arxiv_id")
            if arxiv_id and arxiv_id not in cleared:
                rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arxiv_id", "error_type", "error"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "arxiv_id": row.get("arxiv_id", ""),
                    "error_type": row.get("error_type", ""),
                    "error": row.get("error", ""),
                }
            )


def _stage_8_unavailable_ids(run_dir: Path) -> set[str]:
    path = run_dir / "08_full_markdown" / "unavailable_markdown.csv"
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            arxiv_id = str(row.get("arxiv_id") or "").strip()
            if arxiv_id:
                ids.add(arxiv_id)
    return ids


def _markdown_is_usable(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def load_fulltext_available_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return [
        arxiv_id
        for arxiv_id in read_promoted_arxiv_ids(run_dir)
        if _markdown_is_usable(run_dir / "08_full_markdown" / f"{arxiv_id}.md")
    ]


def _flat_pageindex_nodes(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("nodes"), dict):
        return data["nodes"]
    if isinstance(data, dict):
        return data
    return {}


def _tree_pageindex_nodes(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def walk(node: dict[str, Any], parent_id: str) -> bool:
        node_id = str(node.get("id") or "")
        if not node_id or node_id in found:
            return False
        if node_id != "s.00":
            found[node_id] = node
            if node.get("parent_id") != parent_id:
                return False
        children = node.get("children")
        if children is None:
            return False
        if not isinstance(children, list):
            return False
        return all(isinstance(child, dict) and walk(child, node_id) for child in children)

    if not walk(root, ""):
        return {}
    return found


def _pageindex_artifacts_valid(run_dir: Path, arxiv_id: str) -> bool:
    tree_path = run_dir / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json"
    nodes_path = run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json"
    if not tree_path.exists() or not nodes_path.exists():
        return False
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    nodes = _flat_pageindex_nodes(nodes)
    if not isinstance(tree, dict) or not nodes:
        return False
    if "s.00" in nodes:
        return False
    root = tree.get("root")
    if not isinstance(root, dict) or not root.get("children"):
        return False
    tree_nodes = _tree_pageindex_nodes(root)
    if set(tree_nodes) != set(nodes):
        return False
    required = {"id", "title", "level", "start_line", "end_line", "parent_id", "summary"}
    markdown_path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
    line_count = 0
    if markdown_path.exists():
        try:
            line_count = len(markdown_path.read_text(encoding="utf-8").splitlines())
        except OSError:
            return False
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or not required.issubset(node):
            return False
        if node.get("id") != node_id:
            return False
        tree_node = tree_nodes.get(node_id)
        if not tree_node:
            return False
        for field in required:
            if tree_node.get(field) != node.get(field):
                return False
        try:
            start_line = int(node["start_line"])
            end_line = int(node["end_line"])
            if start_line < 1 or start_line > end_line:
                return False
            if line_count and end_line > line_count:
                return False
        except (TypeError, ValueError):
            return False
    return True


def load_pageindexed_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return [
        arxiv_id
        for arxiv_id in load_fulltext_available_promoted_arxiv_ids(run_dir)
        if _pageindex_artifacts_valid(run_dir, arxiv_id)
    ]


def _stage_10_quarantine_path(run_dir: Path) -> Path:
    return run_dir / "10_verified_evidence" / "quarantined_evidence.csv"


def _stage_10_quarantined_ids(run_dir: Path) -> set[str]:
    path = _stage_10_quarantine_path(run_dir)
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            arxiv_id = str(row.get("arxiv_id") or "").strip()
            if arxiv_id:
                ids.add(arxiv_id)
    return ids


def _record_stage_10_quarantine(run_dir: Path, rows: list[dict[str, str]]) -> None:
    path = _stage_10_quarantine_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                arxiv_id = row.get("arxiv_id")
                if arxiv_id:
                    existing[arxiv_id] = row
    for row in rows:
        existing[row["arxiv_id"]] = row
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arxiv_id", "reason"])
        writer.writeheader()
        for arxiv_id in sorted(existing):
            writer.writerow(
                {
                    "arxiv_id": existing[arxiv_id].get("arxiv_id", ""),
                    "reason": existing[arxiv_id].get("reason", ""),
                }
            )


def _clear_stage_10_quarantine(run_dir: Path, arxiv_ids: Iterable[str]) -> None:
    path = _stage_10_quarantine_path(run_dir)
    if not path.exists():
        return
    cleared = {str(arxiv_id) for arxiv_id in arxiv_ids}
    remaining: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            arxiv_id = str(row.get("arxiv_id") or "").strip()
            if arxiv_id and arxiv_id not in cleared:
                remaining.append(
                    {
                        "arxiv_id": arxiv_id,
                        "reason": str(row.get("reason") or ""),
                    }
                )
    if not remaining:
        path.unlink()
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["arxiv_id", "reason"])
        writer.writeheader()
        writer.writerows(remaining)


def _verified_evidence_claims(run_dir: Path, arxiv_id: str) -> list[dict[str, Any]] | None:
    evidence_path = run_dir / "10_verified_evidence" / f"{arxiv_id}.json"
    if not evidence_path.exists():
        return None
    evidence = _load_json(evidence_path)
    claims = evidence.get("claims") if isinstance(evidence, dict) else None
    if not isinstance(claims, list):
        return None
    return claims


def _claim_grounding_matches_pageindex(
    run_dir: Path,
    arxiv_id: str,
    claim: dict[str, Any],
) -> bool:
    nodes_path = run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json"
    if not nodes_path.exists():
        return False
    try:
        nodes = _flat_pageindex_nodes(json.loads(nodes_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return False
    source_node_id = str(claim.get("source_node_id") or "")
    node = nodes.get(source_node_id)
    if not isinstance(node, dict):
        return False
    source_lines = claim.get("source_lines")
    if not isinstance(source_lines, list) or not source_lines:
        return False
    try:
        node_start = int(node["start_line"])
        node_end = int(node["end_line"])
        line_values = [int(value) for value in source_lines]
    except (KeyError, TypeError, ValueError):
        return False
    return all(node_start <= line <= node_end for line in line_values)


def _verified_evidence_is_valid(run_dir: Path, arxiv_id: str) -> bool:
    claims = _verified_evidence_claims(run_dir, arxiv_id)
    if not claims:
        return False
    return all(
        claim.get("source_node_id")
        and claim.get("source_lines")
        and _claim_grounding_matches_pageindex(run_dir, arxiv_id, claim)
        for claim in claims
    )


def load_verified_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    verified: list[str] = []
    for arxiv_id in load_pageindexed_promoted_arxiv_ids(run_dir):
        if _verified_evidence_is_valid(run_dir, arxiv_id):
            verified.append(arxiv_id)
    return verified


PAGEINDEX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _mechanical_summary(lines: list[str]) -> str:
    text_parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or PAGEINDEX_HEADING_RE.match(stripped):
            continue
        text_parts.append(stripped)
        joined = " ".join(text_parts)
        match = re.search(r"(.+?[.!?])(?:\s|$)", joined)
        if match:
            return match.group(1).strip()[:240]
        if len(joined) >= 240:
            return joined[:240].strip()
    return " ".join(text_parts).strip()[:240]


def _pageindex_node_for_tree(node: dict[str, Any]) -> dict[str, Any]:
    if node.get("id") == "s.00":
        return {
            "id": node["id"],
            "title": node["title"],
            "children": node["children"],
        }
    return {
        "id": node["id"],
        "title": node["title"],
        "level": node["level"],
        "start_line": node["start_line"],
        "end_line": node["end_line"],
        "parent_id": node["parent_id"],
        "summary": node["summary"],
        "children": node["children"],
    }


def _build_pageindex(markdown: str, *, arxiv_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    lines = markdown.splitlines()
    total_lines = max(len(lines), 1)
    root = {
        "id": "s.00",
        "title": "(root)",
        "level": 0,
        "start_line": 1,
        "end_line": total_lines,
        "parent_id": None,
        "summary": "",
        "children": [],
    }
    nodes: dict[str, dict[str, Any]] = {}
    headings: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        match = PAGEINDEX_HEADING_RE.match(line.strip())
        if match:
            headings.append(
                {
                    "level": len(match.group(1)),
                    "title": match.group(2).strip(),
                    "start_line": index,
                    "line_index": index - 1,
                }
            )
    if not headings:
        title = "Document"
        content_lines = lines
        child = {
            "id": "s.01",
            "title": title,
            "level": 1,
            "start_line": 1,
            "end_line": total_lines,
            "parent_id": "s.00",
            "summary": _mechanical_summary(content_lines),
            "children": [],
        }
        root["children"].append(child)
        nodes["s.01"] = {
            key: child[key]
            for key in ("id", "title", "level", "start_line", "end_line", "parent_id", "summary")
        }
        return {"arxiv_id": arxiv_id, "root": _pageindex_node_for_tree(root)}, nodes

    stack: list[tuple[dict[str, Any], list[int]]] = [(root, [])]
    for idx, heading in enumerate(headings):
        while stack and stack[-1][0]["level"] >= heading["level"]:
            stack.pop()
        parent, parent_path = stack[-1] if stack else (root, [])
        current_path = [*parent_path, len(parent["children"]) + 1]
        node_id = "s." + ".".join(f"{part:02d}" for part in current_path)

        next_boundary = total_lines
        for next_heading in headings[idx + 1:]:
            if next_heading["level"] <= heading["level"]:
                next_boundary = next_heading["start_line"] - 1
                break
        end_line = max(heading["start_line"], next_boundary)
        content_lines = lines[heading["line_index"] + 1:end_line]
        node = {
            "id": node_id,
            "title": heading["title"],
            "level": heading["level"],
            "start_line": heading["start_line"],
            "end_line": end_line,
            "parent_id": parent["id"],
            "summary": _mechanical_summary(content_lines),
            "children": [],
        }
        parent["children"].append(node)
        nodes[node_id] = {
            key: node[key]
            for key in ("id", "title", "level", "start_line", "end_line", "parent_id", "summary")
        }
        stack.append((node, current_path))
    return {"arxiv_id": arxiv_id, "root": _pageindex_node_for_tree(root)}, nodes


def _build_pageindex_for_paper(run_dir: Path, arxiv_id: str) -> None:
    markdown_path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
    if not markdown_path.exists():
        raise RuntimeError(f"missing full markdown for {arxiv_id}")
    tree, nodes = _build_pageindex(markdown_path.read_text(encoding="utf-8"), arxiv_id=arxiv_id)
    tree_path = run_dir / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json"
    nodes_path = run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    nodes_path.parent.mkdir(parents=True, exist_ok=True)
    tree_tmp = tree_path.with_suffix(tree_path.suffix + ".tmp")
    nodes_tmp = nodes_path.with_suffix(nodes_path.suffix + ".tmp")
    tree_tmp.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    nodes_tmp.write_text(json.dumps(nodes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tree_tmp.replace(tree_path)
    nodes_tmp.replace(nodes_path)


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


def _edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        edge.get("src"),
        edge.get("dst"),
        edge.get("type"),
        edge.get("source_node_id"),
        tuple(edge.get("source_lines", ())),
    )


def _source_grounding_key(item: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    return (
        str(item.get("source_node_id") or ""),
        tuple(str(value) for value in item.get("source_lines") or []),
    )


def _verified_evidence_source_keys(run_dir: Path, arxiv_id: str) -> set[tuple[str, tuple[str, ...]]]:
    claims = _verified_evidence_claims(run_dir, arxiv_id)
    if claims is None:
        return set()
    return {
        _source_grounding_key(claim)
        for claim in claims
        if claim.get("source_node_id") and claim.get("source_lines")
    }


def merge_verified_graph_fragments(run_dir: Path, arxiv_ids: list[str] | None = None) -> dict[str, Any]:
    fragments_dir = run_dir / "11_verified_graph" / "fragments"
    if not fragments_dir.exists():
        raise FileNotFoundError(f"missing Stage 11 fragments directory: {fragments_dir}")

    if arxiv_ids is None:
        fragment_items = [(path, None) for path in sorted(fragments_dir.glob("*.json"))]
    else:
        fragment_items = [
            (run_dir / verified_graph_fragment_relpath(arxiv_id), arxiv_id)
            for arxiv_id in arxiv_ids
            if (run_dir / verified_graph_fragment_relpath(arxiv_id)).exists()
        ]
    if not fragment_items:
        raise ValueError(f"no Stage 11 fragment JSON files found in {fragments_dir}")

    nodes_by_id: dict[Any, dict[str, Any]] = {}
    edges_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}

    for fragment_path, expected_arxiv_id in fragment_items:
        fragment = json.loads(fragment_path.read_text())
        fragment_arxiv_id = str(expected_arxiv_id or fragment.get("arxiv_id") or fragment_path.stem)
        evidence_path = run_dir / "10_verified_evidence" / f"{fragment_arxiv_id}.json"
        if not evidence_path.exists():
            raise ValueError(f"missing verified evidence for {fragment_arxiv_id}")
        source_keys = _verified_evidence_source_keys(run_dir, fragment_arxiv_id)
        if not source_keys:
            raise ValueError(f"missing verified evidence sources for {fragment_arxiv_id}")
        fragment_node_ids: set[Any] = set()
        for node in fragment.get("nodes", []):
            node_id = node.get("id")
            if not node_id:
                raise ValueError(f"node missing id in {fragment_path}")
            fragment_node_ids.add(node_id)
            if node_id not in nodes_by_id:
                nodes_by_id[node_id] = node
        for edge in fragment.get("edges", []):
            if edge.get("confidence") != "verified":
                raise ValueError(f"unverified edge in {fragment_path}")
            if edge.get("src") not in fragment_node_ids or edge.get("dst") not in fragment_node_ids:
                raise ValueError(f"edge endpoint missing in {fragment_path}")
            if not edge.get("source_node_id"):
                raise ValueError(f"edge missing source_node_id in {fragment_path}")
            if not edge.get("source_lines"):
                raise ValueError(f"edge missing source_lines in {fragment_path}")
            if _source_grounding_key(edge) not in source_keys:
                raise ValueError(f"edge source not found in verified evidence in {fragment_path}")
            key = _edge_key(edge)
            if key not in edges_by_key:
                edges_by_key[key] = edge

    return {
        "nodes": sorted(nodes_by_id.values(), key=lambda node: node["id"]),
        "edges": [edges_by_key[key] for key in sorted(edges_by_key)],
    }


def validate_verified_global_graph(run_dir: Path) -> None:
    path = run_dir / "11_verified_graph" / "global_graph.json"
    graph = _load_json(path)
    if not isinstance(graph, dict):
        raise RuntimeError("global_graph.json must be an object")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("global_graph.json must contain nodes and edges lists")
    node_ids = {
        node.get("id")
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    for edge in edges:
        if not isinstance(edge, dict):
            raise RuntimeError("global_graph.json edges must be objects")
        if edge.get("confidence") != "verified":
            raise RuntimeError("global_graph.json edge confidence must be verified")
        if edge.get("src") not in node_ids or edge.get("dst") not in node_ids:
            raise RuntimeError("global_graph.json edge endpoint missing")
        if not edge.get("source_node_id"):
            raise RuntimeError("global_graph.json edge missing source_node_id")
        if not edge.get("source_lines"):
            raise RuntimeError("global_graph.json edge missing source_lines")


def validate_outline_contract(run_dir: Path) -> None:
    outline = load_outline(run_dir)
    if not isinstance(outline, dict):
        raise RuntimeError("outline.json must be an object")
    book_sections = outline.get("book_sections")
    families = outline.get("families")
    methods = outline.get("methods")
    if not isinstance(book_sections, list) or not isinstance(families, list) or not isinstance(methods, list):
        raise RuntimeError("outline.json must contain book_sections, families, and methods lists")
    expected_sections = list(BOOK_FILE_BY_ID)
    section_ids = [section.get("id") for section in book_sections if isinstance(section, dict)]
    if section_ids != expected_sections:
        raise RuntimeError("outline.json book_sections must use the fixed 8-section order")
    family_ids = {
        str(family.get("id"))
        for family in families
        if isinstance(family, dict) and str(family.get("id") or "").strip()
    }
    if not family_ids:
        raise RuntimeError("outline.json must contain at least one family")
    method_arxiv_ids: list[str] = []
    for method in methods:
        if not isinstance(method, dict):
            raise RuntimeError("outline.json methods must be objects")
        method_id = str(method.get("id") or "").strip()
        arxiv_id = str(method.get("arxiv_id") or "").strip()
        family_id = str(method.get("family_id") or "").strip()
        if not method_id or not arxiv_id or not family_id:
            raise RuntimeError("outline.json methods must include id, arxiv_id, and family_id")
        if family_id not in family_ids:
            raise RuntimeError(f"outline.json method {method_id} references missing family {family_id}")
        method_arxiv_ids.append(arxiv_id)
    verified_ids = load_verified_promoted_arxiv_ids(run_dir)
    if sorted(method_arxiv_ids) != sorted(verified_ids):
        raise RuntimeError("outline.json must contain exactly one method per verified full-text paper")


def _load_weak_edge_count(run_dir: Path) -> int:
    weak_graph_path = run_dir / "05_weak_graph" / "weak_global_graph.json"
    if not weak_graph_path.exists():
        return 0
    weak_graph = json.loads(weak_graph_path.read_text())
    return len(weak_graph.get("edges", []))


def run_stage_11_merge(run_dir: Path, arxiv_ids: list[str] | None = None) -> None:
    graph = merge_verified_graph_fragments(run_dir, arxiv_ids=arxiv_ids)
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
    if executor == "sdk-cli-fallback":
        try:
            return _run_sdk_shard_attempt(run_dir, spec, timeout_seconds)
        except TimeoutError as error:
            if expected_outputs_exist(run_dir, spec):
                return ShardAttemptResult(
                    returncode=0,
                    stdout="",
                    stderr=(
                        "SDK executor timed out after producing expected outputs; "
                        f"accepting artifacts. SDK error: {error}"
                    ),
                    executor="sdk",
                )
            result = _run_cli_shard_attempt(spec, timeout_seconds)
            fallback_note = (
                "SDK executor timed out waiting for app-server notifications; "
                f"retried with CLI executor. SDK error: {error}"
            )
            result.stderr = "\n".join(part for part in (fallback_note, result.stderr) if part)
            return result
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
            sdk_meta = getattr(error, "sdk_meta", None)
            sdk_thread = sdk_meta.get("thread_id") if isinstance(sdk_meta, dict) else "n/a"
            sdk_turn = sdk_meta.get("turn_id") if isinstance(sdk_meta, dict) else "n/a"
            stderr = (
                f"sdk_thread={sdk_thread} sdk_turn={sdk_turn}\n"
                + "".join(
                    traceback.format_exception(type(error), error, error.__traceback__)
                )
            )
            result = ShardAttemptResult(
                returncode=None,
                stdout="",
                stderr=stderr,
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
    if executor not in {"sdk", "cli", "sdk-cli-fallback"}:
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
    data = _load_json(path)
    if isinstance(data, dict) and isinstance(data.get("promoted_papers"), list):
        return _promoted_ids(data)
    if normalize_stage_7_promoted_json(run_dir):
        append_run_log(run_dir, "7", "normalized", "promoted_papers.json rebuilt before downstream load")
    return _promoted_ids(_load_json(path))


def read_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return _promoted_ids_readonly(_load_json(run_dir / "07_scoring" / "promoted_papers.json"))


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
    run_id = run_dir.name
    promoted = load_verified_promoted_arxiv_ids(run_dir)
    if not promoted:
        raise RuntimeError("Stage 11 has no verified full-text papers to merge")
    _clear_stage_10_quarantine(run_dir, promoted)
    specs = [
        ShardSpec(
            stage="11",
            shard_id=_stable_stage_11_shard_id(aid),
            agent="verified_graph_extractor",
            model="gpt-5.4-mini",
            prompt=_stage_11_prompt(run_id, _stable_stage_11_shard_id(aid), [aid]),
            expected_outputs=[verified_graph_fragment_relpath(aid)],
        )
        for aid in promoted
    ]
    if specs:
        append_run_log(run_dir, "11", "dispatching", f"{len(specs)} eligible fragments")
        for spec in specs:
            for relpath in spec.expected_outputs:
                (run_dir / relpath).unlink(missing_ok=True)
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor, force=True)

    still_missing = [
        aid
        for aid in promoted
        if not (run_dir / verified_graph_fragment_relpath(aid)).exists()
    ]
    if still_missing:
        raise RuntimeError(f"Stage 11 still missing fragments: {still_missing}")
    run_stage_11_merge(run_dir, arxiv_ids=promoted)


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


def validate_weak_global_graph(run_dir: Path) -> None:
    path = run_dir / "05_weak_graph" / "weak_global_graph.json"
    graph = _load_json(path)
    if not isinstance(graph, dict):
        raise RuntimeError("weak_global_graph.json must be an object")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("weak_global_graph.json must contain nodes and edges lists")
    node_ids = {
        str(node.get("id"))
        for node in nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    if not node_ids:
        raise RuntimeError("weak_global_graph.json must contain at least one node")
    for edge in edges:
        if not isinstance(edge, dict):
            raise RuntimeError("weak_global_graph.json edges must be objects")
        src = str(edge.get("src") or edge.get("source") or "").strip()
        dst = str(edge.get("dst") or edge.get("target") or "").strip()
        edge_type = str(edge.get("type") or edge.get("relation") or "").strip()
        if not src or not dst or not edge_type:
            raise RuntimeError("weak_global_graph.json edge missing source/target/relation")


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
        validate_outline_contract(run_dir)
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
    validate_outline_contract(run_dir)


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
        "knowledge_gaps_to_explain": _method_gap_scope(run_dir, method, evidence),
        "structured": structured,
        "section_plan": section_plan,
        "neighbors": neighbors,
    }


def _gap_concept_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("concept", "name", "title", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _knowledge_gap_candidates(run_dir: Path) -> list[str]:
    report = _read_json_or_empty(run_dir / "06_expansion" / "knowledge_gap_report.json")
    raw_items: list[Any] = []
    for key in ("knowledge_gaps", "gaps", "confusing_concepts", "missing_prerequisites"):
        value = report.get(key)
        if isinstance(value, list):
            raw_items.extend(value)

    candidates: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        concept = _gap_concept_text(item)
        normalized = concept.lower()
        if concept and normalized not in seen:
            seen.add(normalized)
            candidates.append(concept)
    return sorted(candidates, key=lambda concept: len(concept.split()), reverse=True)


STAGE_5_SCHEMA_VERSION = "stage5_digest_classifier_v1"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_5_paths(run_dir: Path) -> dict[str, Path]:
    expansion = run_dir / "06_expansion"
    return {
        "digest": expansion / "gap_candidates_digest.json",
        "extracted": expansion / "extracted_concepts.json",
        "report": expansion / "knowledge_gap_report.json",
        "queue": expansion / "expansion_need_queue.json",
        "metadata": expansion / "stage5_metadata.json",
    }


def _stage_5_digest_concepts(run_dir: Path) -> set[str]:
    digest = _load_json(_stage_5_paths(run_dir)["digest"])
    candidates = digest.get("candidates") if isinstance(digest, dict) else None
    if not isinstance(candidates, list):
        raise RuntimeError("gap_candidates_digest.json candidates must be a list")
    concepts: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        concept = candidate.get("concept")
        if isinstance(concept, str) and concept.strip():
            concepts.add(concept.strip())
    return concepts


def _stage_5_report_items(report: dict[str, Any]) -> list[Any]:
    out: list[Any] = []
    for key in ("known", "unknown_minor", "knowledge_gaps"):
        items = report.get(key, [])
        if not isinstance(items, list):
            raise RuntimeError(f"knowledge_gap_report.json {key} must be a list")
        out.extend(items)
    return out


def validate_stage_5_outputs(run_dir: Path) -> None:
    paths = _stage_5_paths(run_dir)
    for name, path in paths.items():
        if name == "metadata":
            continue
        if not path.exists():
            raise RuntimeError(f"Stage 5 missing required output: {path.name}")

    digest_concepts = _stage_5_digest_concepts(run_dir)

    extracted = _load_json(paths["extracted"])
    extracted_items = extracted.get("concepts") if isinstance(extracted, dict) else extracted
    if not isinstance(extracted_items, list):
        raise RuntimeError("extracted_concepts.json must contain a concepts list")
    for item in extracted_items:
        concept = _gap_concept_text(item)
        if concept and concept not in digest_concepts:
            raise RuntimeError(
                f"extracted_concepts.json concept is not in digest: {concept}"
            )

    report = _load_json(paths["report"])
    if not isinstance(report, dict):
        raise RuntimeError("knowledge_gap_report.json must be an object")
    for item in _stage_5_report_items(report):
        concept = _gap_concept_text(item)
        if concept and concept not in digest_concepts:
            raise RuntimeError(
                f"knowledge_gap_report.json concept is not in digest: {concept}"
            )

    queue = _load_json(paths["queue"])
    items = queue.get("items") if isinstance(queue, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("expansion_need_queue.json items must be a list")
    if len(items) > 5:
        raise RuntimeError("expansion_need_queue.json must contain at most 5 items")
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("expansion_need_queue.json items must be objects")
        concept = _gap_concept_text(item)
        if not concept:
            raise RuntimeError("expansion_need_queue.json item missing concept")
        if concept not in digest_concepts:
            raise RuntimeError(
                f"expansion_need_queue.json concept is not in digest: {concept}"
            )
        priority = item.get("priority")
        if not isinstance(priority, (int, float)) or float(priority) < 0.70:
            raise RuntimeError(
                f"expansion_need_queue.json priority must be >= 0.70 for {concept}"
            )
        queries = item.get("search_queries")
        valid_queries = [
            query for query in queries or []
            if isinstance(query, str) and query.strip()
        ]
        if len(valid_queries) < 2:
            raise RuntimeError(
                f"expansion_need_queue.json item must include at least 2 search_queries for {concept}"
            )


def write_stage_5_metadata(run_dir: Path) -> None:
    paths = _stage_5_paths(run_dir)
    payload = {
        "schema_version": STAGE_5_SCHEMA_VERSION,
        "agent": "knowledge_gap_classifier",
        "digest_sha256": _sha256_file(paths["digest"]),
        "extracted_sha256": _sha256_file(paths["extracted"]),
        "report_sha256": _sha256_file(paths["report"]),
        "queue_sha256": _sha256_file(paths["queue"]),
        "generated_at": now_iso(),
    }
    _write_json(paths["metadata"], payload)


def stage_5_outputs_valid(run_dir: Path) -> bool:
    paths = _stage_5_paths(run_dir)
    if not all(path.exists() for path in paths.values()):
        return False
    try:
        validate_stage_5_outputs(run_dir)
        metadata = _load_json(paths["metadata"])
    except Exception:
        return False
    return (
        metadata.get("schema_version") == STAGE_5_SCHEMA_VERSION
        and metadata.get("agent") == "knowledge_gap_classifier"
        and metadata.get("digest_sha256") == _sha256_file(paths["digest"])
        and metadata.get("extracted_sha256") == _sha256_file(paths["extracted"])
        and metadata.get("report_sha256") == _sha256_file(paths["report"])
        and metadata.get("queue_sha256") == _sha256_file(paths["queue"])
    )


def _stage_17_learning_suggestions(run_dir: Path) -> str:
    paths = _stage_5_paths(run_dir)
    digest = _load_json(paths["digest"])
    report = _load_json(paths["report"])
    queue = _load_json(paths["queue"])

    candidate_by_concept = {
        candidate.get("concept"): candidate
        for candidate in digest.get("candidates", [])
        if isinstance(candidate, dict) and isinstance(candidate.get("concept"), str)
    }
    queued_items = [
        item for item in queue.get("items", [])
        if isinstance(item, dict) and _gap_concept_text(item)
    ]
    queued_concepts = {_gap_concept_text(item) for item in queued_items}
    report_gap_concepts = []
    seen: set[str] = set()
    for item in report.get("knowledge_gaps", []):
        concept = _gap_concept_text(item)
        if concept and concept not in seen and concept in candidate_by_concept:
            seen.add(concept)
            report_gap_concepts.append(concept)

    def evidence_text(concept: str) -> str:
        candidate = candidate_by_concept.get(concept) or {}
        refs = candidate.get("evidence_refs") or []
        arxiv_ids = [
            str(ref.get("arxiv_id"))
            for ref in refs
            if isinstance(ref, dict) and ref.get("arxiv_id")
        ]
        if arxiv_ids:
            return f" Evidence: {', '.join(arxiv_ids[:3])}."
        return ""

    lines = [
        "# Suggested Knowledge Base Additions",
        "",
        f"Run: {run_dir.name}",
        "",
        "## Queued Expansion Gaps",
        "",
    ]
    if queued_items:
        for item in queued_items:
            concept = _gap_concept_text(item)
            priority = item.get("priority", "")
            lines.append(f"- {concept} (priority: {priority}).{evidence_text(concept)}")
    else:
        lines.append("- No queued expansion gaps.")

    remaining = [concept for concept in report_gap_concepts if concept not in queued_concepts]
    remaining.sort(
        key=lambda concept: candidate_by_concept.get(concept, {}).get("importance", 0),
        reverse=True,
    )
    lines.extend(["", "## Additional High-Importance Gaps", ""])
    if remaining:
        for concept in remaining[:10]:
            importance = candidate_by_concept.get(concept, {}).get("importance", "")
            lines.append(f"- {concept} (importance: {importance}).{evidence_text(concept)}")
    else:
        lines.append("- No additional high-importance gaps.")

    return "\n".join(lines).rstrip() + "\n"


def _concept_match_spans(concept: str, evidence_text: str) -> list[tuple[int, int]]:
    normalized = " ".join(concept.lower().split())
    if not normalized:
        return []
    escaped = r"\s+".join(re.escape(part) for part in normalized.split())
    plural_suffix = "s?" if not normalized.endswith("s") else ""
    return [
        match.span()
        for match in re.finditer(rf"(?<!\w){escaped}{plural_suffix}(?!\w)", evidence_text)
    ]


def _concept_matches_evidence(concept: str, evidence_text: str) -> bool:
    return bool(_concept_match_spans(concept, evidence_text.lower()))


def _evidence_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text
            for item in value.values()
            for text in _evidence_text_values(item)
        ]
    if isinstance(value, list):
        return [
            text
            for item in value
            for text in _evidence_text_values(item)
        ]
    return []


def _method_gap_scope(
    run_dir: Path,
    method: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    explicit = [
        concept
        for concept in (
            _gap_concept_text(item)
            for item in method.get("knowledge_gaps_to_explain") or []
        )
        if concept
    ]
    if explicit:
        return explicit[:3]

    evidence_parts: list[str] = []
    for key in (
        "claims",
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
    ):
        evidence_parts.extend(_evidence_text_values(evidence.get(key) or []))
    evidence_text = " ".join(evidence_parts).lower()

    scoped: list[str] = []
    selected_spans: list[tuple[int, int]] = []
    for concept in _knowledge_gap_candidates(run_dir):
        spans = _concept_match_spans(concept, evidence_text)
        if not spans:
            continue
        if all(
            any(
                start >= selected_start and end <= selected_end
                for selected_start, selected_end in selected_spans
            )
            for start, end in spans
        ):
            continue
        scoped.append(concept)
        selected_spans.extend(spans)
        if len(scoped) >= 3:
            break
    return scoped


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
    if "passed" in verification:
        return verification.get("passed") is True
    summary = verification.get("summary")
    return isinstance(summary, dict) and summary.get("passed") is True


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
    out = run_dir / "17_learning_suggestions" / "knowledge_to_add.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_stage_17_learning_suggestions(run_dir), encoding="utf-8")
    append_run_log(run_dir, "17", "completed", "learning suggestions written")


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
        validate_stage_1_keep_all_contract(run_dir)
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
                "Do not run Stage 2 or later.",
                "Return the standard short success string.",
            ]
        ),
        expected_outputs=["00_input/search_plan.json"],
    )
    run_shards(run_dir, [spec], executor=executor, timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS)
    validate_stage_1_search_plan(run_dir, enforce_query_budget=True)
    _materialize_stage_1_seed_pool(run_dir)
    paper_ids = validate_stage_1_keep_all_contract(run_dir, enforce_query_budget=True)
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
    paper_ids = load_paper_pool_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in paper_ids
        if not (run_dir / "05_weak_graph" / "fragments" / f"{arxiv_id}.json").exists()
    ]
    if primary_artifact_exists(run_dir, "3") and not missing:
        validate_weak_global_graph(run_dir)
        append_run_log(run_dir, "3", "skipped", "weak graph already present")
        return
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


def run_stage_5_aggregate(run_dir: Path) -> None:
    """Stage 5a (Python): build gap_candidates_digest.json from weak graph + evidence."""
    weak_graph = run_dir / "05_weak_graph" / "weak_global_graph.json"
    if not weak_graph.exists():
        raise RuntimeError("Stage 5 requires 05_weak_graph/weak_global_graph.json")
    evidence_dir = run_dir / "04_weak_evidence"
    if not evidence_dir.exists() or not any(evidence_dir.glob("*.json")):
        raise RuntimeError("Stage 5 requires 04_weak_evidence/*.json")
    kb_path = run_dir / "06_expansion" / "known_concepts_snapshot.json"
    if not kb_path.exists():
        raise RuntimeError("Stage 5 requires 06_expansion/known_concepts_snapshot.json")
    digest_path = run_dir / "06_expansion" / "gap_candidates_digest.json"
    if digest_path.exists():
        append_run_log(run_dir, "5a", "skipped", "digest already present")
        return
    digest = build_digest(run_dir, run_id=run_dir.name)
    append_run_log(
        run_dir, "5a", "completed",
        f"digest written; candidates={len(digest.candidates)}",
    )


def run_stage_5(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if stage_5_outputs_valid(run_dir):
        append_run_log(run_dir, "5", "skipped", "knowledge gap outputs already valid")
        return
    run_stage_5_aggregate(run_dir)
    if not (run_dir / "06_expansion" / "gap_candidates_digest.json").exists():
        raise RuntimeError("Stage 5 requires 06_expansion/gap_candidates_digest.json")
    spec = ShardSpec(
        stage="5",
        shard_id="knowledge-gaps",
        agent="knowledge_gap_classifier",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_gap_classifier.toml",
            run_dir.name,
            "5",
            "knowledge-gaps",
            {},
        ),
        expected_outputs=[
            "06_expansion/extracted_concepts.json",
            "06_expansion/knowledge_gap_report.json",
            "06_expansion/expansion_need_queue.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor, force=True)
    validate_stage_5_outputs(run_dir)
    write_stage_5_metadata(run_dir)
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


def _accepted_expansion_rows(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "06_expansion" / "accepted_candidates.csv"
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle) if row.get("arxiv_id")]


def merge_accepted_expansion_into_paper_pool(run_dir: Path) -> int:
    rows = _accepted_expansion_rows(run_dir)
    if not rows:
        return 0
    records = load_paper_pool_records(run_dir)
    existing_ids = {str(record.get("arxiv_id")) for record in records}
    added = 0
    for row in rows:
        arxiv_id = str(row.get("arxiv_id") or "").strip()
        if not arxiv_id or arxiv_id in existing_ids:
            continue
        gap = str(row.get("unknown_concept") or row.get("gap_id") or "").strip()
        record = {
            "arxiv_id": arxiv_id,
            "title": str(row.get("title") or "").strip(),
            "status": "DISCOVERED",
            "source": "knowledge_gap_expansion",
            "added_for_gap": gap,
            "gap_id": str(row.get("gap_id") or "").strip(),
            "why_needed": str(row.get("why_needed") or "").strip(),
            "candidate_role": str(row.get("candidate_role") or "").strip(),
            "expansion_round": 1,
        }
        score = str(row.get("score") or "").strip()
        if score:
            record["score"] = score
        records.append(record)
        existing_ids.add(arxiv_id)
        added += 1
    if added:
        write_paper_pool_records(run_dir, records)
    return added


def validate_stage_6_outputs(run_dir: Path) -> None:
    expansion_dir = run_dir / "06_expansion"
    round_path = expansion_dir / "expansion_round_01.json"
    accepted_path = expansion_dir / "accepted_candidates.csv"
    rejected_path = expansion_dir / "rejected_candidates.csv"
    for path in (round_path, accepted_path, rejected_path):
        if not path.exists():
            raise RuntimeError(f"Stage 6 missing required output: {path.name}")
    round_data = json.loads(round_path.read_text())
    if not isinstance(round_data, dict):
        raise RuntimeError("expansion_round_01.json must be an object")
    if round_data.get("status") not in {"completed", "skipped"}:
        raise RuntimeError("expansion_round_01.json status must be completed or skipped")
    if not isinstance(round_data.get("items"), list):
        raise RuntimeError("expansion_round_01.json items must be a list")
    accepted_rows = _accepted_expansion_rows(run_dir)
    pool_ids = set(load_paper_pool_arxiv_ids(run_dir))
    for row in accepted_rows:
        arxiv_id = str(row.get("arxiv_id") or "").strip()
        if not arxiv_id:
            raise RuntimeError("accepted_candidates.csv rows must include arxiv_id")
        if arxiv_id not in pool_ids:
            raise RuntimeError(f"accepted Stage 6 paper missing from paper_pool.json: {arxiv_id}")
        if not str(row.get("unknown_concept") or row.get("gap_id") or "").strip():
            raise RuntimeError(f"accepted_candidates.csv row missing gap for {arxiv_id}")
        if not str(row.get("why_needed") or "").strip():
            raise RuntimeError(f"accepted_candidates.csv row missing why_needed for {arxiv_id}")


def backfill_expanded_paper_artifacts(
    run_dir: Path,
    *,
    max_workers: int,
    executor: str,
) -> None:
    missing_weak = [
        arxiv_id
        for arxiv_id in load_paper_pool_arxiv_ids(run_dir)
        if not (run_dir / "04_weak_evidence" / f"{arxiv_id}.json").exists()
    ]
    if missing_weak:
        append_run_log(run_dir, "6", "backfill", f"weak evidence for {len(missing_weak)} expanded papers")
        run_stage_2(run_dir, max_workers=max_workers, executor=executor)
    missing_graph = [
        arxiv_id
        for arxiv_id in load_paper_pool_arxiv_ids(run_dir)
        if not (run_dir / "05_weak_graph" / "fragments" / f"{arxiv_id}.json").exists()
    ]
    if missing_graph:
        append_run_log(run_dir, "6", "backfill", f"weak graph for {len(missing_graph)} expanded papers")
        run_stage_3(run_dir, max_workers=max_workers, executor=executor)


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
                items = data.get("items", []) or []
                if isinstance(items, list) and items:
                    round_items.extend(items)
                elif data.get("status") == "completed":
                    round_items.append(data)
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
    merge_accepted_expansion_into_paper_pool(run_dir)
    validate_stage_6_outputs(run_dir)


def run_stage_6(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "6"):
        added = merge_accepted_expansion_into_paper_pool(run_dir)
        validate_stage_6_outputs(run_dir)
        backfill_expanded_paper_artifacts(run_dir, max_workers=max_workers, executor=executor)
        detail = "expansion round already present"
        if added:
            detail += f"; merged {added} accepted papers into pool"
        append_run_log(run_dir, "6", "skipped", detail)
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
    previous_relevance_limit = os.environ.get("SWARN_CODEX_RELEVANCE_SESSION_LIMIT")
    os.environ["SWARN_CODEX_RELEVANCE_SESSION_LIMIT"] = os.environ.get(
        "SWARN_STAGE_6_CODEX_RELEVANCE_SESSION_LIMIT",
        previous_relevance_limit or str(DEFAULT_STAGE_6_CODEX_RELEVANCE_SESSION_LIMIT),
    )
    try:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
    finally:
        if previous_relevance_limit is None:
            os.environ.pop("SWARN_CODEX_RELEVANCE_SESSION_LIMIT", None)
        else:
            os.environ["SWARN_CODEX_RELEVANCE_SESSION_LIMIT"] = previous_relevance_limit
    merge_expansion_shards(run_dir, shard_ids)
    backfill_expanded_paper_artifacts(run_dir, max_workers=max_workers, executor=executor)
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


def run_stage_8(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    del executor
    promoted_ids = read_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not _markdown_is_usable(run_dir / "08_full_markdown" / f"{arxiv_id}.md")
    ]
    if not missing:
        append_run_log(run_dir, "8", "skipped", "markdown already present")
        return
    failures: list[tuple[str, BaseException]] = []
    unavailable: list[tuple[str, BaseException]] = []
    successes: list[str] = []

    def fetch_one(arxiv_id: str) -> None:
        spec = ShardSpec(
            stage="8",
            shard_id=_stable_stage_8_shard_id(arxiv_id),
            agent="direct_markdown_fetcher",
            model="python",
            prompt=f"fetch arxiv markdown for {arxiv_id}",
            expected_outputs=[f"08_full_markdown/{arxiv_id}.md"],
        )
        attempt = _next_shard_attempt(run_dir, spec)
        shard_dir = _shard_dir(run_dir, spec)
        stdout_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
        stderr_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
        output_path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
        attempt_error: BaseException | None = None
        try:
            markdown = _fetch_arxiv_markdown_sync(arxiv_id)
            if not markdown.strip():
                if output_path.exists() and not _markdown_is_usable(output_path):
                    output_path.unlink()
                raise Stage8MarkdownUnavailable(f"empty markdown returned for {arxiv_id}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            tmp_path.write_text(markdown, encoding="utf-8")
            tmp_path.replace(output_path)
            successes.append(arxiv_id)
            result = ShardAttemptResult(
                returncode=0,
                stdout=f"ok: wrote {output_path.relative_to(run_dir)}\n",
                stderr="",
                executor="direct",
            )
            status = "completed"
        except BaseException as error:
            attempt_error = error
            result = ShardAttemptResult(
                returncode=None,
                stdout="",
                stderr="".join(traceback.format_exception(type(error), error, error.__traceback__)),
                executor="direct",
            )
            status = "unavailable" if isinstance(error, Stage8MarkdownUnavailable) else "failed"
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")
        _write_shard_manifest(
            run_dir,
            spec,
            attempt=attempt,
            status=status,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        if status != "completed":
            assert attempt_error is not None
            raise attempt_error

    worker_count = min(max_workers, len(missing))
    if worker_count <= 1:
        for arxiv_id in missing:
            try:
                fetch_one(arxiv_id)
            except BaseException as error:
                if isinstance(error, Stage8MarkdownUnavailable):
                    unavailable.append((arxiv_id, error))
                else:
                    failures.append((arxiv_id, error))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(fetch_one, arxiv_id): arxiv_id for arxiv_id in missing}
            for future in as_completed(futures):
                arxiv_id = futures[future]
                try:
                    future.result()
                except BaseException as error:
                    if isinstance(error, Stage8MarkdownUnavailable):
                        unavailable.append((arxiv_id, error))
                    else:
                        failures.append((arxiv_id, error))
    if successes:
        _clear_stage_8_unavailable_markdown(run_dir, successes)
    if unavailable:
        _record_stage_8_unavailable_markdown(run_dir, unavailable)
        append_run_log(
            run_dir,
            "8",
            "quarantined",
            f"{len(unavailable)} promoted paper(s) kept in Stage 7 but skipped downstream because markdown was unavailable",
        )
    if failures:
        append_run_log(
            run_dir,
            "8",
            "failed",
            f"{len(failures)} markdown fetches failed; first={failures[0][0]}",
        )
        raise RuntimeError(
            f"{len(failures)} markdown fetch(es) failed; first={failures[0][0]}: {failures[0][1]}"
        )
    append_run_log(
        run_dir,
        "8",
        "completed",
        f"markdown fetched for {len(missing) - len(unavailable)} papers; unavailable={len(unavailable)}",
    )


def run_stage_9(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    del executor
    promoted_ids = load_fulltext_available_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not _pageindex_artifacts_valid(run_dir, arxiv_id)
    ]
    failures: list[tuple[str, BaseException]] = []

    def build_one(arxiv_id: str) -> None:
        shard_stem = quote(str(arxiv_id), safe="").replace("%", "pct")
        spec = ShardSpec(
            stage="9",
            shard_id=f"pageindex-{shard_stem}",
            agent="direct_pageindex_builder",
            model="python",
            prompt=f"build pageindex for {arxiv_id}",
            expected_outputs=[
                f"09_pageindex/trees/{arxiv_id}.tree.json",
                f"09_pageindex/nodes/{arxiv_id}.nodes.json",
            ],
        )
        attempt = _next_shard_attempt(run_dir, spec)
        shard_dir = _shard_dir(run_dir, spec)
        stdout_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
        stderr_path = shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
        attempt_error: BaseException | None = None
        try:
            _build_pageindex_for_paper(run_dir, arxiv_id)
            nodes = _load_json(run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json")
            result = ShardAttemptResult(
                returncode=0,
                stdout=f"ok: indexed {arxiv_id}, {len(nodes)} nodes\n",
                stderr="",
                executor="direct",
            )
            status = "completed"
        except BaseException as error:
            attempt_error = error
            result = ShardAttemptResult(
                returncode=None,
                stdout="",
                stderr="".join(traceback.format_exception(type(error), error, error.__traceback__)),
                executor="direct",
            )
            status = "failed"
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")
        _write_shard_manifest(
            run_dir,
            spec,
            attempt=attempt,
            status=status,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        if status != "completed":
            assert attempt_error is not None
            raise attempt_error

    worker_count = min(max_workers, len(missing))
    if worker_count <= 1:
        for arxiv_id in missing:
            try:
                build_one(arxiv_id)
            except BaseException as error:
                failures.append((arxiv_id, error))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(build_one, arxiv_id): arxiv_id for arxiv_id in missing}
            for future in as_completed(futures):
                arxiv_id = futures[future]
                try:
                    future.result()
                except BaseException as error:
                    failures.append((arxiv_id, error))
    if failures:
        append_run_log(run_dir, "9", "failed", f"{len(failures)} PageIndex builds failed; first={failures[0][0]}")
        raise RuntimeError(
            f"{len(failures)} PageIndex build(s) failed; first={failures[0][0]}: {failures[0][1]}"
        )
    append_run_log(run_dir, "9", "completed", f"page indexes ready for {len(promoted_ids)} papers")


def run_stage_10(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    promoted_ids = load_pageindexed_promoted_arxiv_ids(run_dir)
    valid_ids = [
        arxiv_id
        for arxiv_id in promoted_ids
        if _verified_evidence_is_valid(run_dir, arxiv_id)
    ]
    _clear_stage_10_quarantine(run_dir, valid_ids)
    quarantined = _stage_10_quarantined_ids(run_dir)
    initial_zero_claim_ids = {
        arxiv_id
        for arxiv_id in promoted_ids
        if _verified_evidence_claims(run_dir, arxiv_id) == []
    }
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if arxiv_id not in quarantined and not _verified_evidence_is_valid(run_dir, arxiv_id)
    ]

    def evidence_specs(arxiv_ids: list[str], *, shard_prefix: str) -> list[ShardSpec]:
        specs = []
        for idx, chunk in enumerate(chunked(arxiv_ids, 1), start=1):
            shard_id = f"{shard_prefix}-{idx:03d}"
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
        return specs

    specs = evidence_specs(missing, shard_prefix="verified-evidence")
    if specs:
        run_shards(run_dir, specs, max_workers=max_workers, executor=executor, force=True)
    first_pass_zero_claim_ids = [
        arxiv_id
        for arxiv_id in promoted_ids
        if (
            arxiv_id not in quarantined
            and arxiv_id not in initial_zero_claim_ids
            and _verified_evidence_claims(run_dir, arxiv_id) == []
        )
    ]
    retry_specs = evidence_specs(first_pass_zero_claim_ids, shard_prefix="verified-evidence-retry")
    if retry_specs:
        run_shards(run_dir, retry_specs, max_workers=max_workers, executor=executor, force=True)
    quarantines: list[dict[str, str]] = []
    for arxiv_id in promoted_ids:
        if arxiv_id in quarantined and not _verified_evidence_is_valid(run_dir, arxiv_id):
            continue
        claims = _verified_evidence_claims(run_dir, arxiv_id)
        if not claims:
            quarantines.append({"arxiv_id": arxiv_id, "reason": "no_claims"})
            continue
        for claim in claims:
            if not claim.get("source_node_id") or not claim.get("source_lines"):
                raise RuntimeError(f"verified claim for {arxiv_id} is missing source grounding")
    if quarantines:
        _record_stage_10_quarantine(run_dir, quarantines)
        append_run_log(run_dir, "10", "quarantined", f"{len(quarantines)} paper(s) had no verified claims")
    append_run_log(
        run_dir,
        "10",
        "completed",
        f"verified evidence ready for {len(load_verified_promoted_arxiv_ids(run_dir))} papers; quarantined={len(_stage_10_quarantined_ids(run_dir))}",
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
        notification_timeout=_sdk_notification_timeout_seconds(timeout_seconds),
    )


def _sdk_notification_timeout_seconds(timeout_seconds: int) -> float:
    configured = os.environ.get("SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS")
    if configured is None:
        return min(float(DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS), float(timeout_seconds))
    return min(float(configured), float(timeout_seconds))


def _stage_max_workers_env_name(stage: str) -> str:
    safe_stage = re.sub(r"[^A-Za-z0-9]+", "_", str(stage)).strip("_")
    return f"SWARN_STAGE_{safe_stage}_MAX_EFFECTIVE_WORKERS"


def _effective_max_workers(requested_workers: int, *, stage: str | None = None) -> int:
    raw_cap = os.environ.get("SWARN_MAX_EFFECTIVE_WORKERS")
    if raw_cap is None:
        cap = DEFAULT_MAX_EFFECTIVE_WORKERS
    else:
        try:
            cap = int(raw_cap)
        except ValueError as error:
            raise ValueError("SWARN_MAX_EFFECTIVE_WORKERS must be an integer") from error
    if cap < 1:
        raise ValueError("SWARN_MAX_EFFECTIVE_WORKERS must be >= 1")
    if stage is not None:
        stage_key = str(stage)
        env_name = _stage_max_workers_env_name(stage_key)
        raw_stage_cap = os.environ.get(env_name)
        if raw_stage_cap is not None:
            try:
                stage_cap = int(raw_stage_cap)
            except ValueError as error:
                raise ValueError(f"{env_name} must be an integer") from error
            if stage_cap < 1:
                raise ValueError(f"{env_name} must be >= 1")
        else:
            stage_cap = DEFAULT_STAGE_MAX_EFFECTIVE_WORKERS.get(stage_key)
        if stage_cap is not None:
            if stage_cap < 1:
                raise ValueError(f"default cap for stage {stage_key} must be >= 1")
            cap = min(cap, stage_cap)
    return min(requested_workers, cap)


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _read_proc_cmdline(proc_dir: Path) -> list[str]:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _proc_cwd_is_under_repo(proc_dir: Path, repo_root: Path) -> bool:
    try:
        cwd = (proc_dir / "cwd").resolve()
    except OSError:
        return False
    return cwd == repo_root or _path_is_relative_to(cwd, repo_root)


def _find_research_mcp_pids(
    *,
    proc_root: Path = Path("/proc"),
    repo_root: Path = REPO_ROOT,
    current_pid: int | None = None,
) -> list[int]:
    repo_root = repo_root.resolve()
    current_pid = os.getpid() if current_pid is None else current_pid
    pids: list[int] = []
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:
            continue
        cmdline = _read_proc_cmdline(proc_dir)
        joined = " ".join(cmdline)
        if "swarn-auto-research-mcp" not in joined:
            continue
        if _proc_cwd_is_under_repo(proc_dir, repo_root) or str(repo_root) in joined:
            pids.append(pid)
    return sorted(pids)


def cleanup_orphaned_research_mcp_processes(
    *,
    proc_root: Path = Path("/proc"),
    repo_root: Path = REPO_ROOT,
    grace_seconds: float = 2.0,
    kill_func: Any = os.kill,
) -> list[int]:
    pids = _find_research_mcp_pids(proc_root=proc_root, repo_root=repo_root)
    for pid in pids:
        try:
            kill_func(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if pids and grace_seconds > 0:
        sleep(grace_seconds)
    for pid in pids:
        if not (proc_root / str(pid)).exists():
            continue
        try:
            kill_func(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return pids


def cleanup_stage_6_research_mcp_processes(run_dir: Path) -> None:
    try:
        cleaned = cleanup_orphaned_research_mcp_processes()
    except Exception as error:
        append_run_log(run_dir, "6", "cleanup_failed", f"{type(error).__name__}: {error}")
        return
    if cleaned:
        append_run_log(
            run_dir,
            "6",
            "cleanup",
            f"terminated orphaned research MCP processes: {cleaned}",
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

    save_run_state(run_dir, {**load_run_state(run_dir), "status": "completed"})
    print(f"{args.phase} phase complete. run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
