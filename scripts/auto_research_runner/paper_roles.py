from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
METHOD_ARXIV_ID_RE = re.compile(r"^method-\d{4}-\d{4,5}(?:v\d+)?$")


def resolve_paper_metadata(run_dir: Path, arxiv_id: str) -> dict[str, Any]:
    """Resolve paper metadata from paper sources, never generated chapter pages."""
    metadata: dict[str, Any] = {"arxiv_id": arxiv_id}
    for record in _metadata_records(run_dir, arxiv_id):
        if not isinstance(record, dict):
            continue
        title = str(record.get("title") or "").strip()
        if title and (not metadata.get("title") or is_placeholder_method_title(str(metadata.get("title")))):
            metadata["title"] = title
        year = record.get("year")
        if year and not metadata.get("year"):
            metadata["year"] = year
    return metadata


def is_context_only_paper(run_dir: Path, arxiv_id: str) -> bool:
    metadata = resolve_paper_metadata(run_dir, arxiv_id)
    return is_context_only_survey_review_title(str(metadata.get("title") or ""))


def is_context_only_survey_review_title(title: str) -> bool:
    normalized = " ".join(str(title or "").lower().split())
    if not normalized:
        return False
    if any(
        phrase in normalized
        for phrase in (
            "code review",
            "pull request review",
            "review agent benchmark",
            "review effort",
            "review fixing",
            "review response",
        )
    ):
        return False
    if re.search(r"\bsurveys?\b", normalized):
        return True
    return bool(
        re.search(
            r"\b(comprehensive|systematic|literature|scoping)\s+review\b|\breview\s+(?:of|on)\b",
            normalized,
        )
    )


def is_placeholder_method_title(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    if ARXIV_ID_RE.match(normalized):
        return True
    return bool(METHOD_ARXIV_ID_RE.match(normalized.replace(".", "-")))


def is_placeholder_method_id(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    if ARXIV_ID_RE.match(normalized):
        return True
    if ARXIV_ID_RE.match(normalized.replace("-", ".")):
        return True
    return bool(METHOD_ARXIV_ID_RE.match(normalized))


def canonical_method_id_from_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")
    slug = re.sub(r"^(?:a|an|the)-", "", slug)
    if not slug:
        return "method"
    if re.match(r"^\d", slug):
        slug = f"method-{slug}"
    return slug[:80].strip("-") or "method"


def _metadata_records(run_dir: Path, arxiv_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pool_record = _paper_pool_record(run_dir, arxiv_id)
    if pool_record:
        records.append(pool_record)
    for relpath in (
        f"03_overviews/semantic_scholar/{arxiv_id}.json",
        f"04_weak_evidence/{arxiv_id}.json",
    ):
        path = run_dir / relpath
        if path.exists():
            record = _load_json_or_empty(path)
            if isinstance(record, dict):
                record.setdefault("arxiv_id", arxiv_id)
                records.append(record)
    markdown_title = _source_markdown_title(run_dir, arxiv_id)
    if markdown_title:
        records.append({"arxiv_id": arxiv_id, "title": markdown_title})
    return records


def _paper_pool_record(run_dir: Path, arxiv_id: str) -> dict[str, Any]:
    path = run_dir / "02_paper_pool" / "paper_pool.json"
    if not path.exists():
        return {}
    data = _load_json_or_empty(path)
    if isinstance(data, dict):
        if isinstance(data.get("papers"), list):
            for item in data["papers"]:
                if isinstance(item, dict) and str(item.get("arxiv_id") or "") == arxiv_id:
                    return dict(item)
            return {}
        record = data.get(arxiv_id)
        if isinstance(record, dict):
            out = dict(record)
            out.setdefault("arxiv_id", arxiv_id)
            return out
        if record:
            return {"arxiv_id": arxiv_id, "abstract": record}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and str(item.get("arxiv_id") or "") == arxiv_id:
                return dict(item)
    return {}


def _source_markdown_title(run_dir: Path, arxiv_id: str) -> str:
    path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[:80]:
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _load_json_or_empty(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
