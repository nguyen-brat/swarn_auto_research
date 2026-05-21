from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from scripts.auto_research_runner.shared_types import (
    ShardAttemptResult,
    ShardSpec,
    Stage8MarkdownUnavailable,
)


def run_stage_8_impl(
    run_dir: Path,
    *,
    max_workers: int,
    executor: str,
    append_run_log: Callable[[Path, str, str, str], None],
    read_promoted_arxiv_ids: Callable[[Path], list[str]],
    markdown_is_usable: Callable[[Path], bool],
    next_shard_attempt: Callable[[Path, ShardSpec], int],
    shard_dir: Callable[[Path, ShardSpec], Path],
    write_shard_manifest: Callable[..., None],
    fetch_markdown: Callable[[str], str],
    stable_stage_8_shard_id: Callable[[str], str],
    clear_stage_8_unavailable_markdown: Callable[[Path, list[str]], None],
    record_stage_8_unavailable_markdown: Callable[[Path, list[tuple[str, BaseException]]], None],
) -> None:
    del executor
    promoted_ids = read_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not markdown_is_usable(run_dir / "08_full_markdown" / f"{arxiv_id}.md")
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
            shard_id=stable_stage_8_shard_id(arxiv_id),
            agent="direct_markdown_fetcher",
            model="python",
            prompt=f"fetch arxiv markdown for {arxiv_id}",
            expected_outputs=[f"08_full_markdown/{arxiv_id}.md"],
        )
        attempt = next_shard_attempt(run_dir, spec)
        spec_shard_dir = shard_dir(run_dir, spec)
        stdout_path = spec_shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
        stderr_path = spec_shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
        output_path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
        attempt_error: BaseException | None = None
        try:
            markdown = fetch_markdown(arxiv_id)
            if not markdown.strip():
                if output_path.exists() and not markdown_is_usable(output_path):
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
        write_shard_manifest(
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
        clear_stage_8_unavailable_markdown(run_dir, successes)
    if unavailable:
        record_stage_8_unavailable_markdown(run_dir, unavailable)
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


def run_stage_9_impl(
    run_dir: Path,
    *,
    max_workers: int,
    executor: str,
    append_run_log: Callable[[Path, str, str, str], None],
    load_fulltext_available_promoted_arxiv_ids: Callable[[Path], list[str]],
    pageindex_artifacts_valid: Callable[[Path, str], bool],
    next_shard_attempt: Callable[[Path, ShardSpec], int],
    shard_dir: Callable[[Path, ShardSpec], Path],
    write_shard_manifest: Callable[..., None],
    build_pageindex_for_paper: Callable[[Path, str], None],
    load_json: Callable[[Path], Any],
) -> None:
    del executor
    promoted_ids = load_fulltext_available_promoted_arxiv_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if not pageindex_artifacts_valid(run_dir, arxiv_id)
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
        attempt = next_shard_attempt(run_dir, spec)
        spec_shard_dir = shard_dir(run_dir, spec)
        stdout_path = spec_shard_dir / f"{spec.shard_id}.attempt-{attempt}.stdout.txt"
        stderr_path = spec_shard_dir / f"{spec.shard_id}.attempt-{attempt}.stderr.txt"
        attempt_error: BaseException | None = None
        try:
            build_pageindex_for_paper(run_dir, arxiv_id)
            nodes = load_json(run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json")
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
        write_shard_manifest(
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


def run_stage_10_impl(
    run_dir: Path,
    *,
    max_workers: int,
    executor: str,
    append_run_log: Callable[[Path, str, str, str], None],
    load_pageindexed_promoted_arxiv_ids: Callable[[Path], list[str]],
    load_verified_promoted_arxiv_ids: Callable[[Path], list[str]],
    verified_evidence_is_valid: Callable[[Path, str], bool],
    verified_evidence_claims: Callable[[Path, str], list[dict[str, Any]] | None],
    sanitize_verified_evidence: Callable[[Path, str], dict[str, int]],
    clear_stage_10_quarantine: Callable[[Path, Iterable[str]], None],
    stage_10_quarantined_ids: Callable[[Path], set[str]],
    record_stage_10_quarantine: Callable[[Path, list[dict[str, str]]], None],
    chunked: Callable[[list[Any], int], list[list[Any]]],
    generic_agent_prompt: Callable[[str, str, str, str, dict[str, Any]], str],
    run_shards: Callable[..., None],
) -> None:
    promoted_ids = load_pageindexed_promoted_arxiv_ids(run_dir)
    initial_zero_claim_ids = {
        arxiv_id
        for arxiv_id in promoted_ids
        if verified_evidence_claims(run_dir, arxiv_id) == []
    }
    sanitized_counts: dict[str, int] = {}
    for arxiv_id in promoted_ids:
        dropped = sanitize_verified_evidence(run_dir, arxiv_id)
        for field, count in dropped.items():
            sanitized_counts[field] = sanitized_counts.get(field, 0) + count
    valid_ids = [
        arxiv_id
        for arxiv_id in promoted_ids
        if verified_evidence_is_valid(run_dir, arxiv_id)
    ]
    clear_stage_10_quarantine(run_dir, valid_ids)
    quarantined = stage_10_quarantined_ids(run_dir)
    missing = [
        arxiv_id
        for arxiv_id in promoted_ids
        if arxiv_id not in quarantined and not verified_evidence_is_valid(run_dir, arxiv_id)
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
                    prompt=generic_agent_prompt(
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
    for arxiv_id in promoted_ids:
        if arxiv_id in quarantined:
            continue
        dropped = sanitize_verified_evidence(run_dir, arxiv_id)
        for field, count in dropped.items():
            sanitized_counts[field] = sanitized_counts.get(field, 0) + count
    first_pass_zero_claim_ids = [
        arxiv_id
        for arxiv_id in promoted_ids
        if (
            arxiv_id not in quarantined
            and arxiv_id not in initial_zero_claim_ids
            and verified_evidence_claims(run_dir, arxiv_id) == []
        )
    ]
    retry_specs = evidence_specs(first_pass_zero_claim_ids, shard_prefix="verified-evidence-retry")
    if retry_specs:
        run_shards(run_dir, retry_specs, max_workers=max_workers, executor=executor, force=True)
        for arxiv_id in first_pass_zero_claim_ids:
            dropped = sanitize_verified_evidence(run_dir, arxiv_id)
            for field, count in dropped.items():
                sanitized_counts[field] = sanitized_counts.get(field, 0) + count
    if sanitized_counts:
        detail = ", ".join(f"{field}={sanitized_counts[field]}" for field in sorted(sanitized_counts))
        append_run_log(run_dir, "10", "sanitized", f"dropped invalid grounded evidence items: {detail}")
    quarantines: list[dict[str, str]] = []
    for arxiv_id in promoted_ids:
        if arxiv_id in quarantined and not verified_evidence_is_valid(run_dir, arxiv_id):
            continue
        claims = verified_evidence_claims(run_dir, arxiv_id)
        if not claims:
            quarantines.append({"arxiv_id": arxiv_id, "reason": "no_claims"})
            continue
        for claim in claims:
            if not claim.get("source_node_id") or not claim.get("source_lines"):
                raise RuntimeError(f"verified claim for {arxiv_id} is missing source grounding")
    if quarantines:
        record_stage_10_quarantine(run_dir, quarantines)
        append_run_log(run_dir, "10", "quarantined", f"{len(quarantines)} paper(s) had no verified claims")
    append_run_log(
        run_dir,
        "10",
        "completed",
        f"verified evidence ready for {len(load_verified_promoted_arxiv_ids(run_dir))} papers; quarantined={len(stage_10_quarantined_ids(run_dir))}",
    )


def run_stage_11_impl(
    run_dir: Path,
    *,
    max_workers: int,
    executor: str,
    append_run_log: Callable[[Path, str, str, str], None],
    load_verified_promoted_arxiv_ids: Callable[[Path], list[str]],
    clear_stage_10_quarantine: Callable[[Path, Iterable[str]], None],
    build_verified_graph_frame: Callable[[Path, str], Path],
    compile_verified_graph_fragment_from_frame: Callable[[Path, str], int],
    run_shards: Callable[..., None],
    stage_11_prompt: Callable[..., str],
    stable_stage_11_shard_id: Callable[[str], str],
    verified_graph_fragment_relpath: Callable[[str], str],
    verified_graph_fragment_is_valid: Callable[[Path, str], bool],
    verified_graph_fragment_retry_feedback: Callable[[Path, str], str],
    sanitize_verified_graph_fragment: Callable[[Path, str], int],
    run_stage_11_merge: Callable[..., None],
) -> None:
    run_id = run_dir.name
    promoted = load_verified_promoted_arxiv_ids(run_dir)
    if not promoted:
        raise RuntimeError("Stage 11 has no verified full-text papers to merge")
    clear_stage_10_quarantine(run_dir, promoted)
    for aid in promoted:
        build_verified_graph_frame(run_dir, aid)
    specs_by_id = {
        aid: ShardSpec(
            stage="11",
            shard_id=stable_stage_11_shard_id(aid),
            agent="verified_graph_extractor",
            model="gpt-5.4-mini",
            prompt=stage_11_prompt(run_id, stable_stage_11_shard_id(aid), [aid]),
            expected_outputs=[verified_graph_fragment_relpath(aid)],
        )
        for aid in promoted
    }
    specs = [specs_by_id[aid] for aid in promoted]
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
    compiled_edges = sum(
        compile_verified_graph_fragment_from_frame(run_dir, aid)
        for aid in promoted
    )
    if compiled_edges:
        append_run_log(run_dir, "11", "compiled", f"compiled {compiled_edges} claim-grounded edge(s)")
    invalid = [
        aid for aid in promoted
        if not verified_graph_fragment_is_valid(run_dir, aid)
    ]
    if invalid:
        append_run_log(run_dir, "11", "recovery", f"{len(invalid)} invalid verified graph fragment(s) retried")
        retry_specs = [
            ShardSpec(
                stage=specs_by_id[aid].stage,
                shard_id=specs_by_id[aid].shard_id,
                agent=specs_by_id[aid].agent,
                model=specs_by_id[aid].model,
                prompt=stage_11_prompt(
                    run_id,
                    specs_by_id[aid].shard_id,
                    [aid],
                    retry_feedback=verified_graph_fragment_retry_feedback(run_dir, aid),
                ),
                expected_outputs=specs_by_id[aid].expected_outputs,
            )
            for aid in invalid
        ]
        for aid in invalid:
            (run_dir / verified_graph_fragment_relpath(aid)).unlink(missing_ok=True)
        run_shards(run_dir, retry_specs, max_workers=max_workers, executor=executor, force=True)
        compiled_edges = sum(
            compile_verified_graph_fragment_from_frame(run_dir, aid)
            for aid in invalid
        )
        if compiled_edges:
            append_run_log(run_dir, "11", "compiled", f"compiled {compiled_edges} retried claim-grounded edge(s)")
        still_invalid = [
            aid for aid in invalid
            if not verified_graph_fragment_is_valid(run_dir, aid)
        ]
        if still_invalid:
            dropped_edges = sum(
                sanitize_verified_graph_fragment(run_dir, aid)
                for aid in still_invalid
            )
            append_run_log(
                run_dir,
                "11",
                "sanitized",
                f"dropped {dropped_edges} invalid edge(s) from {len(still_invalid)} fragment(s)",
            )
            still_invalid = [
                aid for aid in still_invalid
                if not verified_graph_fragment_is_valid(run_dir, aid)
            ]
            if still_invalid:
                raise RuntimeError(f"Stage 11 still has invalid fragments: {still_invalid}")
    run_stage_11_merge(run_dir, arxiv_ids=promoted)
