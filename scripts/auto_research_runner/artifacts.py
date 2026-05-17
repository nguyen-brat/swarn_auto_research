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
from scripts.auto_research_runner.state import append_run_log
from scripts.auto_research_runner.structured_json import load_structured_json_file


def verified_graph_fragment_filename(arxiv_id: str) -> str:
    return f"{quote(str(arxiv_id), safe='')}.json"


def verified_graph_fragment_relpath(arxiv_id: str) -> str:
    return f"11_verified_graph/fragments/{verified_graph_fragment_filename(arxiv_id)}"


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
        evidence = load_structured_json_file(evidence_path, canonicalize=True)
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
