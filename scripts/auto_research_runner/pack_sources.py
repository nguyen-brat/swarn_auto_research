from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import (
    METHOD_PACK_REQUIRED_SOURCE_SECTIONS,
    METHOD_PACK_SECTION_TITLES,
)


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _page_nodes(run_dir: Path, arxiv_id: str) -> dict[str, Any]:
    data = _read_json_or_empty(run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json")
    if isinstance(data.get("nodes"), dict):
        return data["nodes"]
    return data


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


def _normalized_pack_section_title(title: str) -> str:
    return " ".join(str(title).strip().lower().replace("_", " ").split())


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


# Re-export the canonical section titles list for callers that import from this module.
__all__ = [
    "_read_json_or_empty",
    "_page_nodes",
    "_outline_method_maps",
    "_source_text_from_node",
    "_pack_source_node",
    "_claim_nodes",
    "_structured_nodes",
    "_first_available_nodes",
    "_section_nodes",
    "_normalized_pack_section_title",
    "_gap_concept_text",
    "_knowledge_gap_candidates",
    "_concept_match_spans",
    "_concept_matches_evidence",
    "_evidence_text_values",
    "_method_gap_scope",
    "_first_text",
    "METHOD_PACK_SECTION_TITLES",
    "METHOD_PACK_REQUIRED_SOURCE_SECTIONS",
]
