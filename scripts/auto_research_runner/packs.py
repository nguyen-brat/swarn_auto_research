from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import (
    METHOD_PACK_REQUIRED_SOURCE_SECTIONS,
    METHOD_PACK_SECTION_TITLES,
)
from scripts.auto_research_runner.io_utils import _write_json
from scripts.auto_research_runner.pack_sources import (
    _first_available_nodes,
    _gap_concept_text,
    _method_gap_scope,
    _normalized_pack_section_title,
    _outline_method_maps,
    _read_json_or_empty,
    _section_nodes,
    _structured_nodes,
    _first_text,
)
from scripts.auto_research_runner.state import append_run_log


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
    # Imported here to avoid module-load order issues.
    from scripts.auto_research_runner.chapters import (
        _expected_chapter_pack,
        build_chapter_targets,
        load_outline,
    )

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
