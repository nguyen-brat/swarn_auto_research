from __future__ import annotations

import asyncio
import csv
import os
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import (
    AUTO_RESEARCH_BULK_SEARCH_CONFIG,
    STAGE_1_MAX_NORMAL_QUERIES,
    STAGE_1_MAX_SURVEY_QUERIES,
)
from scripts.auto_research_runner.io_utils import _load_json, _write_json
from scripts.auto_research_runner.paper_pool import _paper_pool_records
from scripts.auto_research_runner.state import append_run_log
from scripts.auto_research_runner.validation import _dedupe_str_list


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
