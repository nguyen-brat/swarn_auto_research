from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import STAGE_5_SCHEMA_VERSION
from scripts.auto_research_runner.io_utils import _load_json, _sha256_file, _write_json
from scripts.auto_research_runner.pack_sources import _gap_concept_text
from scripts.auto_research_runner.state import now_iso


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
    from scripts.auto_research_runner.validation import validate_stage_5_outputs

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
