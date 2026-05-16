from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvidenceRef:
    arxiv_id: str
    slot: str
    snippet: str


@dataclass
class Signals:
    paper_count: int
    core_paper_count: int
    in_slots: list[str]
    is_method_of_core: bool
    alias_hit: bool


@dataclass
class Candidate:
    concept: str
    normalized: str
    importance: float
    signals: Signals
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    graph_neighbors: list[str] = field(default_factory=list)


@dataclass
class Digest:
    run_id: str
    generated_at: str
    params: dict[str, Any]
    kb_summary: dict[str, Any]
    candidates: list[Candidate]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
