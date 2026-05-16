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
