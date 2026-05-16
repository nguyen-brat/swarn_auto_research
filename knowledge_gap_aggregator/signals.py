from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from knowledge_gap_aggregator.alias import normalize

# Maps each concept-bearing field in 04_weak_evidence/*.json to a slot label.
SLOT_BY_FIELD: dict[str, str] = {
    "methods": "method",
    "datasets": "method",
    "benchmarks": "result",
    "baselines": "result",
    "metrics": "result",
    "topic_tags": "abstract",
    "reader_needed_concepts": "reader_needed",
    "mentioned_entities": "mention",
}

_TOKEN = re.compile(r"\w+")


def _importance_score(paper: dict[str, Any]) -> int:
    bu = paper.get("book_usage") or {}
    val = bu.get("importance_score_1_to_5", 0)
    return int(val) if isinstance(val, (int, float)) else 0


def _title_tokens(title: str) -> set[str]:
    """Normalized token set of a paper title — used for word-boundary concept matching."""
    norm = normalize(title)
    return set(_TOKEN.findall(norm))


def _concept_in_title(norm: str, title_tokens: set[str]) -> bool:
    """True iff every word of the normalized concept appears as a whole token in the title.

    Prevents 'vit' from matching 'gravity'. Multi-word concepts are matched as
    a bag-of-tokens.
    """
    parts = _TOKEN.findall(norm)
    return bool(parts) and all(p in title_tokens for p in parts)


def concepts_in_paper(paper: dict[str, Any]) -> list[dict[str, str]]:
    """Walk all concept-bearing fields and emit one entry per (concept, slot).

    The same concept may appear in multiple slots (e.g., methods + title).
    Returned entries: {"raw": ..., "normalized": ..., "slot": ...}
    """
    out: list[dict[str, str]] = []
    title_tokens = _title_tokens(paper.get("title") or "")
    for field, slot in SLOT_BY_FIELD.items():
        for raw in paper.get(field, []) or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            norm = normalize(raw)
            if not norm:
                continue
            out.append({"raw": raw, "normalized": norm, "slot": slot})
            if _concept_in_title(norm, title_tokens):
                out.append({"raw": raw, "normalized": norm, "slot": "title"})
    return out


def paper_count_per_concept(
    evidence: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Distinct papers (arxiv_ids) mentioning each concept."""
    seen: dict[str, set[str]] = defaultdict(set)
    for arxiv_id, paper in evidence.items():
        for c in concepts_in_paper(paper):
            seen[c["normalized"]].add(arxiv_id)
    return {k: len(v) for k, v in seen.items()}


def core_paper_count_per_concept(
    evidence: dict[str, dict[str, Any]],
    *,
    threshold: int = 4,
) -> dict[str, int]:
    """Distinct core papers (importance_score_1_to_5 >= threshold) per concept."""
    seen: dict[str, set[str]] = defaultdict(set)
    for arxiv_id, paper in evidence.items():
        if _importance_score(paper) < threshold:
            continue
        for c in concepts_in_paper(paper):
            seen[c["normalized"]].add(arxiv_id)
    return {k: len(v) for k, v in seen.items()}


_METHOD_OF_CORE_FIELDS = ("methods", "datasets")


def in_slots_per_concept(
    evidence: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Aggregate distinct slot labels a concept appears in, across all papers."""
    slots: dict[str, set[str]] = defaultdict(set)
    for paper in evidence.values():
        for c in concepts_in_paper(paper):
            slots[c["normalized"]].add(c["slot"])
    return {k: sorted(v) for k, v in slots.items()}


def is_method_of_core_per_concept(
    evidence: dict[str, dict[str, Any]],
    *,
    threshold: int = 4,
) -> dict[str, bool]:
    """True if a concept appears in `methods` or `datasets` of any core paper."""
    out: dict[str, bool] = {}
    for paper in evidence.values():
        is_core = _importance_score(paper) >= threshold
        for field in _METHOD_OF_CORE_FIELDS:
            for raw in paper.get(field, []) or []:
                if not isinstance(raw, str):
                    continue
                norm = normalize(raw)
                if not norm:
                    continue
                if is_core:
                    out[norm] = True
                else:
                    out.setdefault(norm, False)
    return out


_METHOD_OF_CORE_GRAPH_EDGES = {"USES", "INTRODUCES", "USES_DATASET", "EXTENDS"}


def _paper_ids(graph: dict[str, Any]) -> set[str]:
    return {n["id"] for n in graph.get("nodes", []) if n.get("type") == "Paper"}


def graph_concept_ids(graph: dict[str, Any]) -> dict[str, str]:
    """Map normalized concept id -> display name, for every non-paper node."""
    out: dict[str, str] = {}
    for n in graph.get("nodes", []):
        if n.get("type") == "Paper":
            continue
        norm = normalize(n["id"])
        if norm:
            out[norm] = n.get("display") or n["id"]
    return out


def graph_paper_count_per_concept(graph: dict[str, Any]) -> dict[str, int]:
    """Distinct paper sources pointing to each non-paper node."""
    papers = _paper_ids(graph)
    seen: dict[str, set[str]] = defaultdict(set)
    for e in graph.get("edges", []):
        if e["src"] in papers and e["dst"] not in papers:
            seen[normalize(e["dst"])].add(e["src"])
    return {k: len(v) for k, v in seen.items()}


def is_method_of_core_via_graph(
    graph: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    *,
    threshold: int = 4,
) -> dict[str, bool]:
    """True if any method-type edge from a core paper reaches the concept."""
    papers = _paper_ids(graph)
    out: dict[str, bool] = {}
    for e in graph.get("edges", []):
        if e.get("type") not in _METHOD_OF_CORE_GRAPH_EDGES:
            continue
        src, dst = e["src"], e["dst"]
        if src in papers and dst not in papers:
            dst_norm = normalize(dst)
            if _importance_score(evidence.get(src, {})) >= threshold:
                out[dst_norm] = True
            else:
                out.setdefault(dst_norm, False)
    return out


def graph_neighbors_per_concept(
    graph: dict[str, Any], *, limit: int = 5,
) -> dict[str, list[str]]:
    """For each non-paper node, up-to-`limit` co-occurring concepts (via shared paper)."""
    papers = _paper_ids(graph)
    display = graph_concept_ids(graph)
    paper_to_concepts: dict[str, set[str]] = defaultdict(set)
    for e in graph.get("edges", []):
        if e["src"] in papers and e["dst"] not in papers:
            paper_to_concepts[e["src"]].add(normalize(e["dst"]))
    co: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for concepts in paper_to_concepts.values():
        clist = list(concepts)
        for i, a in enumerate(clist):
            for b in clist[i + 1:]:
                co[a][b] += 1
                co[b][a] += 1
    out: dict[str, list[str]] = {}
    for k, neigh in co.items():
        ranked = sorted(neigh.items(), key=lambda x: (-x[1], x[0]))[:limit]
        out[k] = [display.get(n, n) for n, _ in ranked]
    return out


_SLOT_WEIGHTS = {
    "title": 1.0,
    "method": 0.8,
    "result": 0.8,
    "abstract": 0.6,
    "reader_needed": 0.4,
    "mention": 0.2,
}


def slot_weight(slots: list[str]) -> float:
    if not slots:
        return 0.2
    return max((_SLOT_WEIGHTS.get(s, 0.2) for s in slots), default=0.2)


def _norm(x: int, cap: int) -> float:
    return min(x, cap) / cap if cap > 0 else 0.0


def importance(
    *,
    paper_count: int,
    core_paper_count: int,
    in_slots: list[str],
    is_method_of_core: bool,
) -> float:
    score = (
        0.35 * _norm(core_paper_count, 3)
        + 0.25 * _norm(paper_count, 5)
        + 0.25 * slot_weight(in_slots)
        + 0.15 * (1.0 if is_method_of_core else 0.0)
    )
    return max(0.0, min(1.0, score))
