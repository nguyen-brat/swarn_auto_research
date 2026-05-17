from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from knowledge_gap_aggregator import build_digest
from scripts.auto_research_runner import stage_fulltext
from scripts.auto_research_runner.artifacts import (
    _build_pageindex_for_paper,
    _claim_grounding_matches_pageindex,
    _clear_stage_10_quarantine,
    _clear_stage_8_unavailable_markdown,
    _markdown_is_usable,
    _pageindex_artifacts_valid,
    _record_stage_10_quarantine,
    _record_stage_8_unavailable_markdown,
    _stable_stage_11_shard_id,
    _stable_stage_8_shard_id,
    _stage_10_quarantined_ids,
    _verified_evidence_claims,
    _verified_evidence_is_valid,
    run_stage_11_merge,
    verified_graph_fragment_relpath,
)
from scripts.auto_research_runner.chapters import (
    _expected_chapter_file,
    _expected_chapter_pack,
    _expected_verification_file,
    _chapter_writer_specs,
    _targets_with_blocking_form_issues,
    _verification_specs,
    _write_verification_summary,
    _build_deterministic_chapter_manifest,
    build_chapter_targets,
    load_outline,
)
from scripts.auto_research_runner.config import (
    ARXIV2MD_MARKDOWN_URL,
    BOOTSTRAP_TIMEOUT_SECONDS,
    DEFAULT_EXECUTOR,
    DEFAULT_STAGE_6_CODEX_RELEVANCE_SESSION_LIMIT,
    DIRECT_SHARD_RULES,
    REPO_ROOT,
    RUNS_ROOT,
    STAGE_8_MARKDOWN_FETCH_TIMEOUT_SECONDS,
)
from scripts.auto_research_runner.io_utils import _load_json, _write_json, chunked
from scripts.auto_research_runner.packs import build_deterministic_stage_13_packs
from scripts.auto_research_runner.paper_pool import (
    load_fulltext_available_promoted_arxiv_ids,
    load_pageindexed_promoted_arxiv_ids,
    load_paper_pool_arxiv_ids,
    load_paper_pool_records,
    load_verified_promoted_arxiv_ids,
    read_promoted_arxiv_ids,
    write_paper_pool_records,
)
from scripts.auto_research_runner.process_cleanup import cleanup_orphaned_research_mcp_processes
from scripts.auto_research_runner.prompts import (
    _generic_agent_prompt,
    _stage_11_prompt,
    _typed_target_ref,
)
from scripts.auto_research_runner.shards import (
    _next_shard_attempt,
    _shard_dir,
    _write_shard_manifest,
    run_deterministic_command,
    run_shards,
)
from scripts.auto_research_runner.shared_types import (
    ShardSpec,
    Stage8MarkdownUnavailable,
)
from scripts.auto_research_runner.stage_5_meta import (
    _stage_17_learning_suggestions,
    stage_5_outputs_valid,
    write_stage_5_metadata,
)
from scripts.auto_research_runner.state import append_run_log, now_iso
from scripts.auto_research_runner.validation import (
    _accepted_expansion_rows,
    _float_score,
    _promoted_ids,
    load_promoted_arxiv_ids,
    normalize_stage_7_candidate_csv,
    normalize_stage_7_promoted_json,
    primary_artifact_exists,
    validate_outline_contract,
    validate_stage_1_keep_all_contract,
    validate_stage_1_search_plan,
    validate_stage_5_outputs,
    validate_stage_6_outputs,
    validate_stage_7_outputs,
    validate_weak_global_graph,
)


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


def load_expansion_gap_items(run_dir: Path) -> list[dict[str, Any]]:
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    if not isinstance(items, list):
        raise RuntimeError("expansion_need_queue.json items must be a list")
    return [item for item in items if isinstance(item, dict)]


def _first_existing_path(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


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


# ─── Stage runners ─────────────────────────────────────────────────────────────


def run_stage_1(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    from scripts.auto_research_runner.stage_1_search import _materialize_stage_1_seed_pool

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
    return stage_fulltext.run_stage_8_impl(
        run_dir,
        max_workers=max_workers,
        executor=executor,
        append_run_log=append_run_log,
        read_promoted_arxiv_ids=read_promoted_arxiv_ids,
        markdown_is_usable=_markdown_is_usable,
        next_shard_attempt=_next_shard_attempt,
        shard_dir=_shard_dir,
        write_shard_manifest=_write_shard_manifest,
        fetch_markdown=_fetch_arxiv_markdown_sync,
        stable_stage_8_shard_id=_stable_stage_8_shard_id,
        clear_stage_8_unavailable_markdown=_clear_stage_8_unavailable_markdown,
        record_stage_8_unavailable_markdown=_record_stage_8_unavailable_markdown,
    )


def run_stage_9(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    return stage_fulltext.run_stage_9_impl(
        run_dir,
        max_workers=max_workers,
        executor=executor,
        append_run_log=append_run_log,
        load_fulltext_available_promoted_arxiv_ids=load_fulltext_available_promoted_arxiv_ids,
        pageindex_artifacts_valid=_pageindex_artifacts_valid,
        next_shard_attempt=_next_shard_attempt,
        shard_dir=_shard_dir,
        write_shard_manifest=_write_shard_manifest,
        build_pageindex_for_paper=_build_pageindex_for_paper,
        load_json=_load_json,
    )


def run_stage_10(run_dir: Path, *, max_workers: int = 1, executor: str = DEFAULT_EXECUTOR) -> None:
    return stage_fulltext.run_stage_10_impl(
        run_dir,
        max_workers=max_workers,
        executor=executor,
        append_run_log=append_run_log,
        load_pageindexed_promoted_arxiv_ids=load_pageindexed_promoted_arxiv_ids,
        load_verified_promoted_arxiv_ids=load_verified_promoted_arxiv_ids,
        verified_evidence_is_valid=_verified_evidence_is_valid,
        verified_evidence_claims=_verified_evidence_claims,
        clear_stage_10_quarantine=_clear_stage_10_quarantine,
        stage_10_quarantined_ids=_stage_10_quarantined_ids,
        record_stage_10_quarantine=_record_stage_10_quarantine,
        chunked=chunked,
        generic_agent_prompt=_generic_agent_prompt,
        run_shards=run_shards,
    )


def run_stage_11(
    run_dir: Path,
    *,
    max_workers: int = 1,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    return stage_fulltext.run_stage_11_impl(
        run_dir,
        max_workers=max_workers,
        executor=executor,
        append_run_log=append_run_log,
        load_verified_promoted_arxiv_ids=load_verified_promoted_arxiv_ids,
        clear_stage_10_quarantine=_clear_stage_10_quarantine,
        run_shards=run_shards,
        stage_11_prompt=_stage_11_prompt,
        stable_stage_11_shard_id=_stable_stage_11_shard_id,
        verified_graph_fragment_relpath=verified_graph_fragment_relpath,
        run_stage_11_merge=run_stage_11_merge,
    )


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
