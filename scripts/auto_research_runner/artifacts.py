from __future__ import annotations

import csv
import json
import re
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
from scripts.auto_research_runner.contract_repair import (
    RepairIssue,
    append_repair_event,
    preserve_raw_artifact,
)
from scripts.auto_research_runner.state import append_run_log
from scripts.auto_research_runner.structured_json import (
    loads_structured_json,
    load_structured_json_file,
)


def verified_graph_fragment_filename(arxiv_id: str) -> str:
    return f"{quote(str(arxiv_id), safe='')}.json"


def verified_graph_fragment_relpath(arxiv_id: str) -> str:
    return f"11_verified_graph/fragments/{verified_graph_fragment_filename(arxiv_id)}"


def verified_graph_frame_relpath(arxiv_id: str) -> str:
    return f"11_verified_graph/frames/{verified_graph_fragment_filename(arxiv_id)}"


def _stable_stage_11_shard_id(arxiv_id: str) -> str:
    stem = verified_graph_fragment_filename(arxiv_id).removesuffix(".json")
    safe_stem = stem.replace("%", "pct")
    return f"vgraph-resume-{safe_stem}"


def _stable_stage_8_shard_id(arxiv_id: str) -> str:
    stem = quote(str(arxiv_id), safe="").replace("%", "pct")
    return f"full-markdown-{stem}"


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
    try:
        evidence = load_structured_json_file(evidence_path)
    except (OSError, json.JSONDecodeError):
        return None
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


def _source_node_exists_in_pageindex(run_dir: Path, arxiv_id: str, item: dict[str, Any]) -> bool:
    nodes_path = run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json"
    if not nodes_path.exists():
        return False
    try:
        nodes = _flat_pageindex_nodes(json.loads(nodes_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return False
    return str(item.get("source_node_id") or "") in nodes


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


STAGE_10_SOURCE_GROUNDED_LIST_FIELDS = (
    "claims",
    "methods",
    "equations",
    "algorithms",
    "hyperparameters",
    "complexity",
    "neighbors",
    "datasets",
    "benchmarks",
    "metrics",
    "baselines",
    "results",
    "limitations",
    "artifacts",
)

STAGE_10_LINE_GROUNDED_LIST_FIELDS = {
    "claims",
    "equations",
    "algorithms",
    "results",
    "limitations",
}


def _stage_10_evidence_item_is_valid(
    run_dir: Path,
    arxiv_id: str,
    item: dict[str, Any],
    *,
    require_lines: bool,
) -> bool:
    if not item.get("source_node_id"):
        return False
    source_lines = item.get("source_lines")
    if require_lines or source_lines:
        return _claim_grounding_matches_pageindex(run_dir, arxiv_id, item)
    return _source_node_exists_in_pageindex(run_dir, arxiv_id, item)


def sanitize_verified_evidence(run_dir: Path, arxiv_id: str) -> dict[str, int]:
    evidence_path = run_dir / "10_verified_evidence" / f"{arxiv_id}.json"
    if not evidence_path.exists():
        return {}
    try:
        raw_text = evidence_path.read_text(encoding="utf-8")
        try:
            json.loads(raw_text)
            repaired_json_syntax = False
        except json.JSONDecodeError:
            repaired_json_syntax = True
        evidence = loads_structured_json(raw_text)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(evidence, dict):
        return {}

    dropped: dict[str, int] = {}
    changed = False
    for field in STAGE_10_SOURCE_GROUNDED_LIST_FIELDS:
        values = evidence.get(field)
        if values is None:
            continue
        if not isinstance(values, list):
            evidence[field] = []
            dropped[field] = 1
            changed = True
            continue

        kept: list[dict[str, Any]] = []
        dropped_count = 0
        for item in values:
            if not isinstance(item, dict):
                dropped_count += 1
                continue
            if _stage_10_evidence_item_is_valid(
                run_dir,
                arxiv_id,
                item,
                require_lines=(field in STAGE_10_LINE_GROUNDED_LIST_FIELDS),
            ):
                kept.append(item)
                continue
            dropped_count += 1
        if dropped_count:
            evidence[field] = kept
            dropped[field] = dropped_count
            changed = True

    if changed or repaired_json_syntax:
        raw = preserve_raw_artifact(run_dir, evidence_path)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        issues = []
        if repaired_json_syntax:
            issues.append(
                RepairIssue(
                    kind="repaired_json_syntax",
                    detail="rewrote repairable malformed JSON into strict canonical JSON",
                )
            )
        if dropped:
            detail = ", ".join(f"{field}={count}" for field, count in sorted(dropped.items()))
            issues.append(
                RepairIssue(
                    kind="dropped_invalid_verified_evidence",
                    detail=f"dropped invalid grounded evidence items: {detail}",
                )
            )
        append_repair_event(
            run_dir,
            stage="10",
            artifact_path=evidence_path,
            raw=raw,
            outcome="accepted",
            issues=issues,
        )
    return dropped


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


def verified_graph_fragment_retry_feedback(run_dir: Path, arxiv_id: str) -> str:
    fragment_path = run_dir / verified_graph_fragment_relpath(arxiv_id)
    try:
        fragment = json.loads(fragment_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return "\n".join(
            [
                "Previous Stage 11 fragment failed validation.",
                "The previous fragment could not be parsed as JSON; regenerate it from the Stage 11 frame.",
                "Do not reuse malformed JSON or direct source_node_id/source_lines edges.",
                f"fragment_json_error={type(error).__name__}: {error}",
            ]
        )
    if not isinstance(fragment, dict):
        return "\n".join(
            [
                "Previous Stage 11 fragment failed validation.",
                "The previous fragment was not a JSON object; regenerate it from the Stage 11 frame.",
                "Do not reuse malformed JSON or direct source_node_id/source_lines edges.",
                f"fragment_json_error=fragment root type was {type(fragment).__name__}",
            ]
        )
    fragment_arxiv_id = str(fragment.get("arxiv_id") or arxiv_id)
    claims = _verified_evidence_claims(run_dir, fragment_arxiv_id) or []
    source_keys = {
        _source_grounding_key(claim)
        for claim in claims
        if claim.get("source_node_id") and claim.get("source_lines")
    }
    node_ids = {
        node.get("id")
        for node in fragment.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    invalid_edges: list[dict[str, Any]] = []
    for edge in fragment.get("edges", []):
        if not isinstance(edge, dict):
            invalid_edges.append({"reason": "edge is not an object", "edge": edge})
            continue
        reasons = []
        if not edge.get("claim_id"):
            reasons.append("missing claim_id")
        if edge.get("confidence") != "verified":
            reasons.append("confidence is not verified")
        if edge.get("src") not in node_ids or edge.get("dst") not in node_ids:
            reasons.append("edge endpoint missing from fragment nodes")
        if not edge.get("source_node_id"):
            reasons.append("missing source_node_id")
        if not edge.get("source_lines"):
            reasons.append("missing source_lines")
        if edge.get("source_node_id") and edge.get("source_lines") and _source_grounding_key(edge) not in source_keys:
            reasons.append("source_node_id + source_lines pair is not an exact Stage 10 claim source")
        if reasons:
            invalid_edges.append({"reason": "; ".join(reasons), "edge": edge})

    allowed_sources = [
        {
            "source_node_id": claim.get("source_node_id"),
            "source_lines": claim.get("source_lines"),
            "claim": str(claim.get("text") or "")[:240],
        }
        for claim in claims
        if claim.get("source_node_id") and claim.get("source_lines")
    ]
    payload = {
        "arxiv_id": fragment_arxiv_id,
        "invalid_edges": invalid_edges[:20],
        "allowed_stage10_claim_sources": allowed_sources[:60],
    }
    return "\n".join(
        [
            "Previous Stage 11 fragment failed validation.",
            "Repair the fragment instead of repeating the same grounding mistake.",
            "For every edge, copy one exact source_node_id + source_lines pair from allowed_stage10_claim_sources.",
            "Do not merge adjacent line ranges, narrow line ranges, invent section ids, or use source pairs from PageIndex directly.",
            f"validation_feedback={json.dumps(payload, sort_keys=True)}",
        ]
    )


STAGE_11_EDGE_TYPES = [
    "INTRODUCES",
    "USES",
    "SOLVES",
    "EVALUATES_ON",
    "MEASURES_WITH",
    "HAS_RESULT",
    "HAS_LIMITATION",
    "COMPARES_TO",
    "IMPROVES_ON",
    "BELONGS_TO",
]


def _graph_node_id(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9+#@._/-]+", " ", str(value or "").lower())
    return " ".join(normalized.split())


def _add_frame_node(nodes_by_id: dict[str, dict[str, str]], node_id: str, node_type: str, display: str) -> None:
    node_id = _graph_node_id(node_id)
    if not node_id:
        return
    nodes_by_id.setdefault(
        node_id,
        {"id": node_id, "type": node_type, "display": str(display or node_id)},
    )


def _stage_11_frame_claims(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    claims = evidence.get("claims") if isinstance(evidence.get("claims"), list) else []
    framed_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            continue
        if not claim.get("source_node_id") or not claim.get("source_lines"):
            continue
        framed_claims.append(
            {
                "claim_id": f"c{index:03d}",
                "claim": str(claim.get("text") or ""),
                "claim_type": str(claim.get("claim_type") or ""),
                "source_node_id": claim.get("source_node_id"),
                "source_lines": claim.get("source_lines"),
            }
        )
    return framed_claims


def build_verified_graph_frame(run_dir: Path, arxiv_id: str) -> Path:
    evidence_path = run_dir / "10_verified_evidence" / f"{arxiv_id}.json"
    evidence = load_structured_json_file(evidence_path)
    if not isinstance(evidence, dict):
        raise ValueError(f"verified evidence for {arxiv_id} must be an object")

    nodes_by_id: dict[str, dict[str, str]] = {}
    _add_frame_node(nodes_by_id, arxiv_id, "Paper", str(evidence.get("title") or arxiv_id))

    weak_path = run_dir / "05_weak_graph" / "fragments" / f"{arxiv_id}.json"
    if weak_path.exists():
        weak = json.loads(weak_path.read_text())
        for node in weak.get("nodes", []):
            if isinstance(node, dict):
                _add_frame_node(
                    nodes_by_id,
                    str(node.get("id") or ""),
                    str(node.get("type") or "Concept"),
                    str(node.get("display") or node.get("id") or ""),
                )

    field_types = {
        "methods": "Method",
        "datasets": "Dataset",
        "benchmarks": "Benchmark",
        "metrics": "Metric",
        "baselines": "Method",
        "results": "Result",
        "limitations": "Limitation",
        "algorithms": "Method",
        "hyperparameters": "Concept",
        "complexity": "Concept",
        "neighbors": "Method",
    }
    for field, node_type in field_types.items():
        values = evidence.get(field)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            label = item.get("name") or item.get("text") or item.get("method") or item.get("title")
            if label:
                _add_frame_node(nodes_by_id, str(label), node_type, str(label))

    edge_types = set(STAGE_11_EDGE_TYPES)
    if weak_path.exists():
        weak = json.loads(weak_path.read_text())
        for edge in weak.get("edges", []):
            if isinstance(edge, dict) and edge.get("type"):
                edge_types.add(str(edge["type"]))

    frame = {
        "arxiv_id": arxiv_id,
        "claims": _stage_11_frame_claims(evidence),
        "allowed_nodes": sorted(nodes_by_id.values(), key=lambda node: node["id"]),
        "allowed_edge_types": sorted(edge_types),
        "output_contract": {
            "edge_fields": ["claim_id", "src", "dst", "type", "confidence"],
            "note": "Use claim_id for grounding. Python copies source_node_id and source_lines from claims.",
        },
    }
    frame_path = run_dir / verified_graph_frame_relpath(arxiv_id)
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path.write_text(json.dumps(frame, indent=2, sort_keys=True) + "\n")
    return frame_path


def compile_verified_graph_fragment_from_frame(run_dir: Path, arxiv_id: str) -> int:
    frame_path = run_dir / verified_graph_frame_relpath(arxiv_id)
    fragment_path = run_dir / verified_graph_fragment_relpath(arxiv_id)
    if not frame_path.exists() or not fragment_path.exists():
        return 0
    frame = json.loads(frame_path.read_text())
    fragment = json.loads(fragment_path.read_text())
    claims_by_id = {
        claim.get("claim_id"): claim
        for claim in frame.get("claims", [])
        if isinstance(claim, dict) and claim.get("claim_id")
    }
    allowed_nodes = {
        node.get("id"): node
        for node in frame.get("allowed_nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    for node in fragment.get("proposed_nodes", []):
        if isinstance(node, dict) and node.get("id"):
            allowed_nodes.setdefault(
                _graph_node_id(node["id"]),
                {
                    "id": _graph_node_id(node["id"]),
                    "type": str(node.get("type") or "Concept"),
                    "display": str(node.get("display") or node["id"]),
                },
            )
    allowed_edge_types = set(frame.get("allowed_edge_types") or STAGE_11_EDGE_TYPES)

    compiled_edges: list[dict[str, Any]] = []
    passthrough_edges: list[dict[str, Any]] = []
    dropped_claim_edges = 0
    for edge in fragment.get("edges", []):
        if not isinstance(edge, dict):
            continue
        claim_id = edge.get("claim_id")
        if not claim_id:
            passthrough_edges.append(edge)
            continue
        claim = claims_by_id.get(claim_id)
        src = _graph_node_id(edge.get("src"))
        dst = _graph_node_id(edge.get("dst"))
        edge_type = str(edge.get("type") or "")
        if not claim or src not in allowed_nodes or dst not in allowed_nodes or edge_type not in allowed_edge_types:
            dropped_claim_edges += 1
            continue
        compiled = dict(edge)
        compiled.update(
            {
                "src": src,
                "dst": dst,
                "type": edge_type,
                "confidence": "verified",
                "source_node_id": claim["source_node_id"],
                "source_lines": claim["source_lines"],
            }
        )
        compiled_edges.append(compiled)

    if not compiled_edges and not dropped_claim_edges:
        return 0

    raw = preserve_raw_artifact(run_dir, fragment_path)
    referenced = {arxiv_id}
    for edge in compiled_edges + passthrough_edges:
        referenced.add(edge.get("src"))
        referenced.add(edge.get("dst"))
    nodes_by_id = {
        node_id: node
        for node_id, node in allowed_nodes.items()
        if node_id in referenced
    }
    for node in fragment.get("nodes", []):
        if isinstance(node, dict) and node.get("id") in referenced:
            nodes_by_id.setdefault(node["id"], node)

    fragment["nodes"] = sorted(nodes_by_id.values(), key=lambda node: node["id"])
    fragment["edges"] = passthrough_edges + compiled_edges
    fragment.pop("proposed_nodes", None)
    fragment_path.write_text(json.dumps(fragment, indent=2, sort_keys=True) + "\n")
    issues: list[RepairIssue] = []
    if dropped_claim_edges:
        issues.append(
            RepairIssue(
                kind="claim_id_compile_dropped_edge",
                detail=f"dropped {dropped_claim_edges} edge(s) with claim_id, endpoints, or type not allowed by the Stage 11 frame",
            )
        )
    if compiled_edges:
        issues.append(
            RepairIssue(
                kind="claim_id_compile_canonicalized",
                detail=f"compiled {len(compiled_edges)} claim_id edge(s) with exact Stage 10 source grounding",
            )
        )
    append_repair_event(
        run_dir,
        stage="11",
        artifact_path=fragment_path,
        raw=raw,
        outcome="accepted",
        issues=issues,
    )
    return len(compiled_edges)


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
            if not edge.get("claim_id"):
                raise ValueError(f"edge missing claim_id in {fragment_path}")
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


def sanitize_verified_graph_fragment(run_dir: Path, arxiv_id: str) -> int:
    fragment_path = run_dir / verified_graph_fragment_relpath(arxiv_id)
    fragment = json.loads(fragment_path.read_text())
    fragment_arxiv_id = str(fragment.get("arxiv_id") or arxiv_id)
    source_keys = _verified_evidence_source_keys(run_dir, fragment_arxiv_id)
    if not source_keys:
        return 0

    nodes = fragment.get("nodes", [])
    if not isinstance(nodes, list):
        return 0
    node_ids = {node.get("id") for node in nodes if isinstance(node, dict) and node.get("id")}

    valid_edges: list[dict[str, Any]] = []
    for edge in fragment.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if not edge.get("claim_id"):
            continue
        if edge.get("confidence") != "verified":
            continue
        if edge.get("src") not in node_ids or edge.get("dst") not in node_ids:
            continue
        if not edge.get("source_node_id") or not edge.get("source_lines"):
            continue
        if _source_grounding_key(edge) not in source_keys:
            continue
        valid_edges.append(edge)

    original_edges = fragment.get("edges", [])
    if not isinstance(original_edges, list):
        original_edges = []
    dropped = len(original_edges) - len(valid_edges)
    if dropped <= 0:
        return 0

    raw = preserve_raw_artifact(run_dir, fragment_path)
    referenced = {fragment_arxiv_id}
    for edge in valid_edges:
        referenced.add(edge["src"])
        referenced.add(edge["dst"])
    valid_nodes = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("id")
        and (node.get("id") in referenced or node.get("type") == "Paper")
    ]
    fragment["nodes"] = valid_nodes
    fragment["edges"] = valid_edges
    fragment_path.write_text(json.dumps(fragment, indent=2, sort_keys=True) + "\n")
    append_repair_event(
        run_dir,
        stage="11",
        artifact_path=fragment_path,
        raw=raw,
        outcome="attempted",
        issues=[
            RepairIssue(
                kind="dropped_invalid_verified_edge",
                detail=f"dropped {dropped} edge(s) with invalid endpoint, confidence, or Stage 10 source grounding",
            )
        ],
    )
    return dropped


def verified_graph_fragment_is_valid(run_dir: Path, arxiv_id: str) -> bool:
    try:
        merge_verified_graph_fragments(run_dir, arxiv_ids=[arxiv_id])
    except (json.JSONDecodeError, OSError, ValueError):
        return False
    return True


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
