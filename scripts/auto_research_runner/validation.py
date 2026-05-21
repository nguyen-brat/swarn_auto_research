from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.artifacts import (
    _markdown_is_usable,
    _pageindex_artifacts_valid,
    _stage_8_unavailable_ids,
)
from scripts.auto_research_runner.config import (
    MIN_BOOTSTRAP_PAPER_POOL,
    PRIMARY_ARTIFACTS,
    REPO_ROOT,
    STAGE_1_MAX_ASPECTS,
    STAGE_1_MAX_NORMAL_QUERIES,
    STAGE_1_MAX_SURVEY_QUERIES,
    STAGE_1_MIN_ASPECTS,
)
from scripts.auto_research_runner.contract_repair import RepairIssue, preserve_raw_artifact
from scripts.auto_research_runner.io_utils import _load_csv_rows, _load_json
from scripts.auto_research_runner.paper_pool import (
    _duplicate_ids,
    _kept_paper_ids,
    _paper_pool_ids,
    _promoted_ids,
    _seed_pool_ids,
    _seed_pool_kept_count,
    load_final_candidate_promoted_arxiv_ids,
    load_paper_pool_arxiv_ids,
    read_promoted_arxiv_ids,
)
from scripts.auto_research_runner.paper_roles import (
    canonical_method_id_from_title,
    is_context_only_paper,
    is_placeholder_method_id,
    is_placeholder_method_title,
    resolve_paper_metadata,
)
from scripts.auto_research_runner.state import append_run_log


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


def primary_artifact_exists(run_dir: Path, stage: str) -> bool:
    artifacts = PRIMARY_ARTIFACTS.get(str(stage), ())
    return bool(artifacts) and all((run_dir / artifact).exists() for artifact in artifacts)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _float_score(row: dict[str, str], *, path_name: str) -> float:
    try:
        return float(row.get("final_score", ""))
    except ValueError as error:
        raise RuntimeError(f"{path_name} final_score must be numeric for {row.get('arxiv_id')}") from error


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


def load_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    path = run_dir / "07_scoring" / "promoted_papers.json"
    data = _load_json(path)
    if isinstance(data, dict) and isinstance(data.get("promoted_papers"), list):
        return _promoted_ids(data)
    if normalize_stage_7_promoted_json(run_dir):
        append_run_log(run_dir, "7", "normalized", "promoted_papers.json rebuilt before downstream load")
    return _promoted_ids(_load_json(path))


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
    # Imported here to avoid module-load cycle: chapters imports validation transitively.
    from scripts.auto_research_runner.chapters import load_outline
    from swarn_research_mcp.research_book import BOOK_FILE_BY_ID

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
    verified_ids = load_final_candidate_promoted_arxiv_ids(run_dir)
    if sorted(method_arxiv_ids) != sorted(verified_ids):
        raise RuntimeError("outline.json must contain exactly one method per final candidate paper")


def normalize_outline_to_verified_papers(run_dir: Path) -> dict[str, Any]:
    # Imported here to avoid module-load cycle: chapters imports validation transitively.
    from scripts.auto_research_runner.chapters import load_outline

    outline_path = run_dir / "12_taxonomy" / "outline.json"
    outline = load_outline(run_dir)
    if not isinstance(outline, dict):
        return {
            "dropped_extra_methods": 0,
            "dropped_duplicate_methods": 0,
            "dropped_context_only_methods": 0,
            "dropped_empty_families": 0,
            "renamed_method_ids": 0,
            "hydrated_method_titles": 0,
            "missing_verified_methods": 0,
        }
    methods = outline.get("methods")
    families = outline.get("families")
    if not isinstance(methods, list) or not isinstance(families, list):
        return {
            "dropped_extra_methods": 0,
            "dropped_duplicate_methods": 0,
            "dropped_context_only_methods": 0,
            "dropped_empty_families": 0,
            "renamed_method_ids": 0,
            "hydrated_method_titles": 0,
            "missing_verified_methods": 0,
        }

    verified_ids = load_final_candidate_promoted_arxiv_ids(run_dir)
    verified_set = set(verified_ids)
    seen_arxiv_ids: set[str] = set()
    methods_by_family: dict[str, list[str]] = {}
    kept_methods: list[dict[str, Any]] = []
    dropped_extra_methods = 0
    dropped_duplicate_methods = 0
    dropped_context_only_methods = 0
    renamed_method_ids = 0
    hydrated_method_titles = 0
    method_id_renames: dict[str, str] = {}
    used_method_ids = {
        str(method.get("id") or "").strip()
        for method in methods
        if isinstance(method, dict) and str(method.get("id") or "").strip()
    }

    for method in methods:
        if not isinstance(method, dict):
            kept_methods.append(method)
            continue
        arxiv_id = str(method.get("arxiv_id") or "").strip()
        if arxiv_id not in verified_set:
            if arxiv_id and is_context_only_paper(run_dir, arxiv_id):
                dropped_context_only_methods += 1
            else:
                dropped_extra_methods += 1
            continue
        if arxiv_id in seen_arxiv_ids:
            dropped_duplicate_methods += 1
            continue
        seen_arxiv_ids.add(arxiv_id)
        method = _canonicalized_outline_method(
            run_dir,
            method,
            used_method_ids=used_method_ids,
            method_id_renames=method_id_renames,
        )
        if method.pop("_hydrated_method_title", False):
            hydrated_method_titles += 1
        if method.pop("_renamed_method_id", False):
            renamed_method_ids += 1
        kept_methods.append(method)
        method_id = str(method.get("id") or "").strip()
        family_id = str(method.get("family_id") or "").strip()
        if method_id and family_id:
            methods_by_family.setdefault(family_id, []).append(method_id)

    kept_method_ids = {
        str(method.get("id") or "").strip()
        for method in kept_methods
        if isinstance(method, dict) and str(method.get("id") or "").strip()
    }
    for method in kept_methods:
        if not isinstance(method, dict):
            continue
        neighbors = method.get("neighbor_method_ids")
        if isinstance(neighbors, list):
            method["neighbor_method_ids"] = [
                renamed
                for neighbor_id in neighbors
                if (renamed := method_id_renames.get(str(neighbor_id), str(neighbor_id))) in kept_method_ids
            ]

    kept_families: list[dict[str, Any]] = []
    dropped_empty_families = 0
    rewritten_family_method_ids = 0
    for family in families:
        if not isinstance(family, dict):
            kept_families.append(family)
            continue
        family_id = str(family.get("id") or "").strip()
        kept_method_ids = methods_by_family.get(family_id, [])
        if not kept_method_ids:
            dropped_empty_families += 1
            continue
        updated_family = dict(family)
        original_method_ids = family.get("method_ids")
        if original_method_ids != kept_method_ids:
            rewritten_family_method_ids += 1
        updated_family["method_ids"] = kept_method_ids
        kept_families.append(updated_family)

    dropped_parts = 0
    pruned_part_family_ids = 0
    if isinstance(outline.get("parts"), list):
        kept_family_ids = {
            str(family.get("id") or "").strip()
            for family in kept_families
            if isinstance(family, dict)
        }
        kept_parts: list[dict[str, Any]] = []
        for part in outline["parts"]:
            if not isinstance(part, dict):
                kept_parts.append(part)
                continue
            family_ids = part.get("family_ids")
            if not isinstance(family_ids, list):
                kept_parts.append(part)
                continue
            kept_part_family_ids = [
                str(family_id).strip()
                for family_id in family_ids
                if str(family_id).strip() in kept_family_ids
            ]
            if not kept_part_family_ids:
                dropped_parts += 1
                continue
            updated_part = dict(part)
            if kept_part_family_ids != [str(family_id).strip() for family_id in family_ids]:
                pruned_part_family_ids += 1
            updated_part["family_ids"] = kept_part_family_ids
            kept_parts.append(updated_part)
        outline["parts"] = kept_parts

    missing_verified_methods = len(verified_set - seen_arxiv_ids)
    changed = (
        dropped_extra_methods
        or dropped_duplicate_methods
        or dropped_context_only_methods
        or renamed_method_ids
        or hydrated_method_titles
        or dropped_empty_families
        or rewritten_family_method_ids
        or dropped_parts
        or pruned_part_family_ids
    )
    repair_raw: dict[str, str] = {}
    repair_issues: list[dict[str, Any]] = []
    if changed:
        raw = preserve_raw_artifact(run_dir, outline_path)
        repair_raw = {"raw_artifact": raw.raw_artifact, "raw_sha256": raw.raw_sha256}
        if dropped_extra_methods:
            repair_issues.append(
                RepairIssue(
                    kind="dropped_extra_method",
                    detail=f"dropped {dropped_extra_methods} method(s) whose arxiv_id was not verified",
                ).to_json()
            )
        if dropped_duplicate_methods:
            repair_issues.append(
                RepairIssue(
                    kind="dropped_duplicate_method",
                    detail=f"dropped {dropped_duplicate_methods} duplicate method(s)",
                ).to_json()
            )
        if dropped_context_only_methods:
            repair_issues.append(
                RepairIssue(
                    kind="dropped_context_only_method",
                    detail=f"dropped {dropped_context_only_methods} survey/review context-only method(s)",
                ).to_json()
            )
        if hydrated_method_titles:
            repair_issues.append(
                RepairIssue(
                    kind="hydrated_method_title",
                    detail=f"hydrated {hydrated_method_titles} placeholder method title(s)",
                ).to_json()
            )
        if renamed_method_ids:
            repair_issues.append(
                RepairIssue(
                    kind="renamed_placeholder_method_id",
                    detail=f"renamed {renamed_method_ids} placeholder method id(s)",
                ).to_json()
            )
        if dropped_empty_families:
            repair_issues.append(
                RepairIssue(
                    kind="dropped_empty_family",
                    detail=f"dropped {dropped_empty_families} family/families with no kept methods",
                ).to_json()
            )
        if rewritten_family_method_ids:
            repair_issues.append(
                RepairIssue(
                    kind="rewritten_family_method_ids",
                    detail=f"rewrote method_ids for {rewritten_family_method_ids} family/families to match kept methods",
                ).to_json()
            )
        if dropped_parts:
            repair_issues.append(
                RepairIssue(kind="dropped_empty_part", detail=f"dropped {dropped_parts} empty part(s)").to_json()
            )
        if pruned_part_family_ids:
            repair_issues.append(
                RepairIssue(
                    kind="pruned_part_family_ids",
                    detail=f"pruned invalid family_ids from {pruned_part_family_ids} part(s)",
                ).to_json()
            )
        outline["methods"] = kept_methods
        outline["families"] = kept_families
        tmp_path = outline_path.with_suffix(outline_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(outline, indent=2, sort_keys=True) + "\n")
        tmp_path.replace(outline_path)

    return {
        "dropped_extra_methods": dropped_extra_methods,
        "dropped_duplicate_methods": dropped_duplicate_methods,
        "dropped_context_only_methods": dropped_context_only_methods,
        "renamed_method_ids": renamed_method_ids,
        "hydrated_method_titles": hydrated_method_titles,
        "dropped_empty_families": dropped_empty_families,
        "rewritten_family_method_ids": rewritten_family_method_ids,
        "dropped_parts": dropped_parts,
        "pruned_part_family_ids": pruned_part_family_ids,
        "missing_verified_methods": missing_verified_methods,
        "repair_raw_artifact": repair_raw.get("raw_artifact", ""),
        "repair_raw_sha256": repair_raw.get("raw_sha256", ""),
        "repair_issues": repair_issues,
    }


def _canonicalized_outline_method(
    run_dir: Path,
    method: dict[str, Any],
    *,
    used_method_ids: set[str],
    method_id_renames: dict[str, str],
) -> dict[str, Any]:
    out = dict(method)
    arxiv_id = str(out.get("arxiv_id") or "").strip()
    metadata = resolve_paper_metadata(run_dir, arxiv_id) if arxiv_id else {}
    title = str(out.get("title") or "").strip()
    metadata_title = str(metadata.get("title") or "").strip()
    if metadata_title and is_placeholder_method_title(title):
        out["title"] = metadata_title
        out["_hydrated_method_title"] = True
        title = metadata_title
    old_id = str(out.get("id") or "").strip()
    if is_placeholder_method_id(old_id) or (arxiv_id and old_id == f"method-{arxiv_id.replace('.', '-')}"):
        base = canonical_method_id_from_title(title or metadata_title or arxiv_id)
        new_id = base
        suffix = 2
        used_method_ids.discard(old_id)
        while new_id in used_method_ids:
            new_id = f"{base}-{suffix}"
            suffix += 1
        if new_id != old_id:
            out["id"] = new_id
            out["_renamed_method_id"] = True
            method_id_renames[old_id] = new_id
            used_method_ids.add(new_id)
    out.setdefault("known_concepts_assumed", [])
    out.setdefault("knowledge_gaps_to_explain", [])
    out.setdefault("neighbor_method_ids", [])
    return out


def validate_bootstrap_stage_0_10_contract(run_dir: Path) -> None:
    """Fail closed if a bootstrap child skipped real discovery."""
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


def validate_stage_5_outputs(run_dir: Path) -> None:
    # Imported here to avoid an early import cycle with stage_5_meta.
    from scripts.auto_research_runner.pack_sources import _gap_concept_text
    from scripts.auto_research_runner.stage_5_meta import (
        _stage_5_digest_concepts,
        _stage_5_paths,
        _stage_5_report_items,
    )

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


def validate_stage_6_outputs(run_dir: Path) -> None:
    expansion_dir = run_dir / "06_expansion"
    round_path = expansion_dir / "expansion_round_01.json"
    accepted_path = expansion_dir / "accepted_candidates.csv"
    rejected_path = expansion_dir / "rejected_candidates.csv"
    for path in (round_path, accepted_path, rejected_path):
        _require(path.exists(), f"Stage 6 missing required output: {path.name}")
    round_data = json.loads(round_path.read_text())
    _require(isinstance(round_data, dict), "expansion_round_01.json must be an object")
    _require(
        round_data.get("status") in {"completed", "skipped"},
        "expansion_round_01.json status must be completed or skipped",
    )
    _require(isinstance(round_data.get("items"), list), "expansion_round_01.json items must be a list")
    pool_ids = set(load_paper_pool_arxiv_ids(run_dir))
    for row in _accepted_expansion_rows(run_dir):
        arxiv_id = str(row.get("arxiv_id") or "").strip()
        _require(bool(arxiv_id), "accepted_candidates.csv rows must include arxiv_id")
        _require(arxiv_id in pool_ids, f"accepted Stage 6 paper missing from paper_pool.json: {arxiv_id}")
        _require(
            bool(str(row.get("unknown_concept") or row.get("gap_id") or "").strip()),
            f"accepted_candidates.csv row missing gap for {arxiv_id}",
        )
        _require(
            bool(str(row.get("why_needed") or "").strip()),
            f"accepted_candidates.csv row missing why_needed for {arxiv_id}",
        )


def _accepted_expansion_rows(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "06_expansion" / "accepted_candidates.csv"
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle) if row.get("arxiv_id")]
