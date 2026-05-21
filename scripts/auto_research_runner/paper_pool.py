from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.artifacts import (
    _markdown_is_usable,
    _pageindex_artifacts_valid,
    _verified_evidence_is_valid,
)
from scripts.auto_research_runner.io_utils import _load_json, _write_json
from scripts.auto_research_runner.paper_roles import is_context_only_paper


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


def read_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return _promoted_ids_readonly(_load_json(run_dir / "07_scoring" / "promoted_papers.json"))


def load_fulltext_available_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return [
        arxiv_id
        for arxiv_id in read_promoted_arxiv_ids(run_dir)
        if _markdown_is_usable(run_dir / "08_full_markdown" / f"{arxiv_id}.md")
    ]


def load_pageindexed_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return [
        arxiv_id
        for arxiv_id in load_fulltext_available_promoted_arxiv_ids(run_dir)
        if _pageindex_artifacts_valid(run_dir, arxiv_id)
    ]


def load_verified_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    verified: list[str] = []
    for arxiv_id in load_pageindexed_promoted_arxiv_ids(run_dir):
        if _verified_evidence_is_valid(run_dir, arxiv_id):
            verified.append(arxiv_id)
    return verified


def load_final_candidate_promoted_arxiv_ids(run_dir: Path) -> list[str]:
    return [
        arxiv_id
        for arxiv_id in load_verified_promoted_arxiv_ids(run_dir)
        if not is_context_only_paper(run_dir, arxiv_id)
    ]


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
