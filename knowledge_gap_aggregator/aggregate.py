from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge_gap_aggregator.alias import is_known, normalize
from knowledge_gap_aggregator.schema import (
    Candidate,
    Digest,
    EvidenceRef,
    Signals,
)
from knowledge_gap_aggregator.signals import (
    concepts_in_paper,
    core_paper_count_per_concept,
    graph_concept_ids,
    graph_neighbors_per_concept,
    graph_paper_count_per_concept,
    importance,
    in_slots_per_concept,
    is_method_of_core_per_concept,
    is_method_of_core_via_graph,
    paper_count_per_concept,
)

# Hard caps applied at write time so a noisy run cannot inflate the digest.
_SNIPPET_MAX_CHARS = 200
_NEIGHBOR_NAME_MAX_CHARS = 80
_DIGEST_SIZE_HARD_LIMIT_BYTES = 100_000  # 100 KB; tests pin this.


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else {}


def _load_evidence(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ev_dir = run_dir / "04_weak_evidence"
    if not ev_dir.exists():
        return out
    for path in ev_dir.glob("*.json"):
        data = _load_json(path)
        if isinstance(data, dict):
            out[data.get("arxiv_id", path.stem)] = data
    return out


def _evidence_display_index(evidence: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map normalized -> first observed raw form across evidence files."""
    seen: dict[str, str] = {}
    for paper in evidence.values():
        for c in concepts_in_paper(paper):
            seen.setdefault(c["normalized"], c["raw"])
    return seen


def _union_paper_count(
    evidence: dict[str, dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, int]:
    """Distinct paper sources per concept, unioning evidence mentions and graph edges."""
    papers_in_graph = {n["id"] for n in graph.get("nodes", []) if n.get("type") == "Paper"}
    seen: dict[str, set[str]] = defaultdict(set)
    for arxiv_id, paper in evidence.items():
        for c in concepts_in_paper(paper):
            seen[c["normalized"]].add(arxiv_id)
    for e in graph.get("edges", []):
        if e["src"] in papers_in_graph and e["dst"] not in papers_in_graph:
            seen[normalize(e["dst"])].add(e["src"])
    return {k: len(v) for k, v in seen.items()}


def _evidence_refs_for(
    normalized: str,
    evidence: dict[str, dict[str, Any]],
    *,
    max_refs: int = 2,
    max_chars: int = _SNIPPET_MAX_CHARS,
) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for arxiv_id, paper in evidence.items():
        seen_slot: str | None = None
        for c in concepts_in_paper(paper):
            if c["normalized"] == normalized:
                seen_slot = c["slot"]
                break
        if seen_slot is None:
            continue
        snippet_pool = " ".join(paper.get("solution", []) or paper.get("problem", []) or [])
        snippet = (snippet_pool or normalized)[:max_chars]
        refs.append(EvidenceRef(arxiv_id=arxiv_id, slot=seen_slot, snippet=snippet))
        if len(refs) >= max_refs:
            break
    return refs


def _cap_neighbors(names: list[str]) -> list[str]:
    return [n[:_NEIGHBOR_NAME_MAX_CHARS] for n in names[:5]]


def build_digest(
    run_dir: Path,
    *,
    run_id: str | None = None,
    top_n: int = 100,
    hard_cap: int = 120,
    min_score: float = 0.30,
) -> Digest:
    run_dir = Path(run_dir)
    evidence = _load_evidence(run_dir)
    graph = _load_json(run_dir / "05_weak_graph" / "weak_global_graph.json")
    kb = _load_json(run_dir / "06_expansion" / "known_concepts_snapshot.json")

    paper_count_evidence_only = paper_count_per_concept(evidence)
    paper_count_graph_only = graph_paper_count_per_concept(graph)
    paper_count_union = _union_paper_count(evidence, graph)

    cpc = core_paper_count_per_concept(evidence)
    slots = in_slots_per_concept(evidence)
    imoc_evidence = is_method_of_core_per_concept(evidence)
    imoc_graph = is_method_of_core_via_graph(graph, evidence)
    neighbors = graph_neighbors_per_concept(graph)

    evidence_display = _evidence_display_index(evidence)
    graph_display = graph_concept_ids(graph)

    # Universe: evidence concepts ∪ graph non-paper nodes (normalized keys).
    universe = (
        set(paper_count_evidence_only)
        | set(slots)
        | set(paper_count_graph_only)
        | set(graph_display)
    )

    candidates: list[Candidate] = []
    dropped: list[dict[str, str]] = []

    for norm in sorted(universe):
        raw = evidence_display.get(norm) or graph_display.get(norm, norm)
        if is_known(raw, kb) or is_known(norm, kb):
            dropped.append({"concept": raw, "reason": "known"})
            continue
        p = paper_count_union.get(norm, 0)
        sl = slots.get(norm, [])
        if p <= 1 and set(sl).issubset({"mention", "reader_needed"}) and not imoc_graph.get(norm, False):
            dropped.append({"concept": raw, "reason": "too_minor"})
            continue
        sigs = Signals(
            paper_count=p,
            core_paper_count=cpc.get(norm, 0),
            in_slots=sl,
            is_method_of_core=imoc_evidence.get(norm, False) or imoc_graph.get(norm, False),
            alias_hit=False,
        )
        imp = importance(
            paper_count=sigs.paper_count,
            core_paper_count=sigs.core_paper_count,
            in_slots=sigs.in_slots,
            is_method_of_core=sigs.is_method_of_core,
        )
        if imp < min_score and sigs.core_paper_count < 2:
            dropped.append({"concept": raw, "reason": "low_score"})
            continue
        candidates.append(Candidate(
            concept=raw[:_NEIGHBOR_NAME_MAX_CHARS],
            normalized=norm[:_NEIGHBOR_NAME_MAX_CHARS],
            importance=imp,
            signals=sigs,
            evidence_refs=_evidence_refs_for(norm, evidence),
            graph_neighbors=_cap_neighbors(neighbors.get(norm, [])),
        ))

    candidates.sort(key=lambda c: c.importance, reverse=True)
    top = candidates[:top_n]
    extras = [c for c in candidates[top_n:] if c.signals.core_paper_count >= 2]
    selected = (top + extras)[:hard_cap]

    aliases_map = kb.get("aliases") or {}
    digest = Digest(
        run_id=run_id or run_dir.name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        params={
            "top_n": top_n,
            "hard_cap": hard_cap,
            "min_importance_score": min_score,
            "kb_alias_normalized": True,
            "size_hard_limit_bytes": _DIGEST_SIZE_HARD_LIMIT_BYTES,
        },
        kb_summary={
            "known_count": len(aliases_map),
            "sample_aliases": list(aliases_map.keys())[:10],
        },
        candidates=selected,
    )

    out_path = run_dir / "06_expansion" / "gap_candidates_digest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(digest.to_dict(), indent=2)
    if len(payload.encode("utf-8")) > _DIGEST_SIZE_HARD_LIMIT_BYTES:
        raise RuntimeError(
            f"gap_candidates_digest.json exceeded size budget "
            f"({len(payload.encode('utf-8'))} > {_DIGEST_SIZE_HARD_LIMIT_BYTES} bytes); "
            f"tighten snippet/neighbor caps or lower hard_cap."
        )
    out_path.write_text(payload)

    log_path = run_dir / "06_expansion" / "aggregator_log.json"
    log_path.write_text(json.dumps({"dropped": dropped}, indent=2))

    return digest
