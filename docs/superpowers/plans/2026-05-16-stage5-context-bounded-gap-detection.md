# Stage 5 Context-Bounded Gap Detection — Implementation Plan (rev 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single agent that reads the entire weak global graph + every weak-evidence file with a deterministic Python aggregator that emits a bounded ≤72 KB digest, and a small classifier agent that reads only that digest.

**Architecture:** New `knowledge_gap_aggregator/` Python module (`schema.py`, `alias.py`, `signals.py`, `aggregate.py`) does the heavy reading and writes `gap_candidates_digest.json`. A new `knowledge_gap_classifier` agent replaces `knowledge_gap_detector` and reads only the digest plus the KB aliases. Stage 5 splits into 5a (Python) + 5b (agent); stage number and downstream contracts unchanged. **Old detector kept on disk through M1 and only removed in M1.5 after regression validation on an existing run.**

**Tech Stack:** Python 3.13, `dataclasses`, `pytest`, existing `ShardSpec`/`run_shards` dispatch. **No `networkx`** — community detection / `bridge_score` deferred.

**Spec reference:** `docs/superpowers/specs/2026-05-16-stage5-context-bounded-gap-detection-design.md` (rev 2)

**Revision note (rev 2):** Previous revision used a fabricated `04_weak_evidence` schema with a `concepts[]` array and `slot` field. Real schema has concepts spread across `methods`/`datasets`/`benchmarks`/`baselines`/`mentioned_entities`/`reader_needed_concepts`/`topic_tags` and importance under `book_usage.importance_score_1_to_5`. Signals and fixtures rewritten. `bridge_score` and `networkx` dropped from v1. `top_n` raised 40 → 100. Detector deletion split into its own milestone (M1.5).

---

## File structure

**New files:**
- `knowledge_gap_aggregator/__init__.py`
- `knowledge_gap_aggregator/schema.py` — `Candidate`, `Signals`, `EvidenceRef`, `Digest` dataclasses
- `knowledge_gap_aggregator/alias.py` — `normalize(s)`, `is_known(concept, kb)`
- `knowledge_gap_aggregator/signals.py` — `SLOT_BY_FIELD`, per-signal pure functions, composite `importance(...)`
- `knowledge_gap_aggregator/aggregate.py` — `build_digest(run_dir, run_id=..., top_n=100, hard_cap=120)`
- `.codex/agents/knowledge_gap_classifier.toml`
- `.agents/skills/knowledge-gap-classification/SKILL.md`
- `tests/fixtures/weak_graph_mini/` — `weak_global_graph.json`, `known_concepts_snapshot.json`, three real-schema `04_weak_evidence/*.json` files
- `tests/test_gap_aggregator_alias.py`
- `tests/test_gap_aggregator_signals.py`
- `tests/test_gap_aggregator_digest.py`
- `tests/test_gap_classifier_skill.py`
- `tests/test_stage_5_pipeline.py`

**Modified files:**
- `scripts/run_auto_research.py` — split `run_stage_5` into `run_stage_5_aggregate` + agent dispatch
- `.agents/skills/auto-research-orchestrator/SKILL.md` — agent name reference (M2)
- `tests/test_codex_scaffold.py` — `EXPECTED_AGENTS` / `EXPECTED_SKILLS` (M2)
- `tests/test_auto_research_runner_cli.py` — stage-5 dispatch test (M2)

**Deleted files (M1.5, after regression sign-off):**
- `.codex/agents/knowledge_gap_detector.toml`
- `.agents/skills/knowledge-gap-detection/`

---

# Milestone M0 — Aggregator only

Produces `gap_candidates_digest.json` alongside the existing pipeline. Old agent untouched.

---

### Task 1: Build real-schema fixture

**Files:**
- Create: `tests/fixtures/weak_graph_mini/weak_global_graph.json`
- Create: `tests/fixtures/weak_graph_mini/known_concepts_snapshot.json`
- Create: `tests/fixtures/weak_graph_mini/04_weak_evidence/p1.json`
- Create: `tests/fixtures/weak_graph_mini/04_weak_evidence/p2.json`
- Create: `tests/fixtures/weak_graph_mini/04_weak_evidence/p3.json`

- [ ] **Step 1: weak_global_graph.json**

```json
{
  "nodes": [
    {"id": "p1", "type": "Paper", "display": "Paper One: ViT for Vision"},
    {"id": "p2", "type": "Paper", "display": "Paper Two: CLIP Variants"},
    {"id": "p3", "type": "Paper", "display": "Paper Three: ASR Baselines"},
    {"id": "vit", "type": "Method", "display": "ViT"},
    {"id": "clip vision encoder", "type": "Method", "display": "CLIP vision encoder"},
    {"id": "transformer", "type": "Method", "display": "Transformer"},
    {"id": "wav2vec", "type": "Method", "display": "wav2vec"},
    {"id": "mel spectrogram", "type": "Dataset", "display": "Mel spectrogram"}
  ],
  "edges": [
    {"src": "p1", "dst": "vit", "type": "USES", "confidence": "weak"},
    {"src": "p1", "dst": "transformer", "type": "USES", "confidence": "weak"},
    {"src": "p2", "dst": "vit", "type": "USES", "confidence": "weak"},
    {"src": "p2", "dst": "clip vision encoder", "type": "PROPOSES", "confidence": "weak"},
    {"src": "p2", "dst": "transformer", "type": "USES", "confidence": "weak"},
    {"src": "p3", "dst": "wav2vec", "type": "USES", "confidence": "weak"},
    {"src": "p3", "dst": "mel spectrogram", "type": "USES", "confidence": "weak"}
  ]
}
```

- [ ] **Step 2: known_concepts_snapshot.json**

```json
{
  "known_count": 1,
  "aliases": {
    "transformer": ["transformer", "transformers"]
  }
}
```

- [ ] **Step 3: 04_weak_evidence/p1.json (real schema, importance=5 = core paper)**

```json
{
  "arxiv_id": "p1",
  "title": "ViT for Vision",
  "year": 2021,
  "trust_level": "OVERVIEW_DERIVED",
  "paper_type": "method",
  "topic_tags": ["computer vision"],
  "problem": ["image classification needs a new architecture"],
  "solution": ["apply a Transformer directly to image patches"],
  "methods": ["ViT", "Transformer"],
  "datasets": [],
  "benchmarks": [],
  "metrics": [],
  "baselines": [],
  "results": [],
  "limitations": [],
  "mentioned_entities": [],
  "mentioned_papers": [],
  "reader_needed_concepts": ["attention"],
  "book_usage": {
    "possible_chapters": ["Vision Transformers"],
    "role": "central",
    "importance_score_1_to_5": 5
  }
}
```

- [ ] **Step 4: 04_weak_evidence/p2.json (importance=4 = core)**

```json
{
  "arxiv_id": "p2",
  "title": "CLIP Variants",
  "year": 2023,
  "trust_level": "OVERVIEW_DERIVED",
  "paper_type": "method",
  "topic_tags": ["multimodal"],
  "problem": ["align text and image embeddings"],
  "solution": ["contrastive training over a vision encoder"],
  "methods": ["CLIP vision encoder", "Transformer"],
  "datasets": ["LAION"],
  "benchmarks": ["ImageNet zero-shot"],
  "metrics": [],
  "baselines": ["ViT"],
  "results": [],
  "limitations": [],
  "mentioned_entities": [],
  "mentioned_papers": [],
  "reader_needed_concepts": [],
  "book_usage": {
    "possible_chapters": ["CLIP Family"],
    "role": "central",
    "importance_score_1_to_5": 4
  }
}
```

- [ ] **Step 5: 04_weak_evidence/p3.json (importance=2 = non-core)**

```json
{
  "arxiv_id": "p3",
  "title": "ASR Baselines",
  "year": 2020,
  "trust_level": "OVERVIEW_DERIVED",
  "paper_type": "application",
  "topic_tags": ["speech"],
  "problem": ["benchmark ASR"],
  "solution": ["compare wav2vec and mel-spectrogram baselines"],
  "methods": ["wav2vec", "Mel spectrogram"],
  "datasets": [],
  "benchmarks": ["LibriSpeech"],
  "metrics": ["WER"],
  "baselines": [],
  "results": [],
  "limitations": [],
  "mentioned_entities": [],
  "mentioned_papers": [],
  "reader_needed_concepts": [],
  "book_usage": {
    "possible_chapters": ["ASR Background"],
    "role": "support",
    "importance_score_1_to_5": 2
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/weak_graph_mini/
git commit -m "feat: weak_graph_mini fixture (real 04_weak_evidence schema)"
```

---

### Task 2: Schema dataclasses

**Files:**
- Create: `knowledge_gap_aggregator/__init__.py`
- Create: `knowledge_gap_aggregator/schema.py`

- [ ] **Step 1: `__init__.py`**

```python
"""Stage 5 aggregator: turn weak graph + evidence into a bounded digest."""
from knowledge_gap_aggregator.schema import Candidate, Digest, EvidenceRef, Signals

__all__ = ["Candidate", "Digest", "EvidenceRef", "Signals"]
```

(`build_digest` export added in Task 8.)

- [ ] **Step 2: `schema.py`**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add knowledge_gap_aggregator/
git commit -m "feat: scaffold knowledge_gap_aggregator with schema"
```

---

### Task 3: Alias normalization (TDD)

**Files:**
- Create: `knowledge_gap_aggregator/alias.py`
- Create: `tests/test_gap_aggregator_alias.py`

- [ ] **Step 1: Tests**

```python
from knowledge_gap_aggregator.alias import is_known, normalize


def test_normalize_lowercases_and_strips():
    assert normalize("  CLIP Vision Encoder ") == "clip vision encoder"

def test_normalize_collapses_whitespace():
    assert normalize("Mel   Spectrogram") == "mel spectrogram"

def test_normalize_strips_trailing_punctuation():
    assert normalize("Transformer.") == "transformer"
    assert normalize("ViT,") == "vit"

def test_normalize_handles_hyphens_as_spaces():
    assert normalize("wav2vec-2.0") == "wav2vec 2.0"

def test_is_known_exact_alias():
    kb = {"aliases": {"transformer": ["transformer", "transformers"]}}
    assert is_known("Transformer", kb) is True
    assert is_known("transformers", kb) is True

def test_is_known_normalized_match():
    kb = {"aliases": {"mel spectrogram": ["mel spectrogram"]}}
    assert is_known("Mel  Spectrogram.", kb) is True

def test_is_known_returns_false_for_unknown():
    kb = {"aliases": {"transformer": ["transformer"]}}
    assert is_known("CLIP vision encoder", kb) is False

def test_is_known_empty_kb():
    assert is_known("anything", {"aliases": {}}) is False
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_gap_aggregator_alias.py -v
```

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import re
from typing import Any

_PUNCT_TRAIL = re.compile(r"[.,;:!?]+$")
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    out = s.strip().lower().replace("-", " ")
    out = _WS.sub(" ", out)
    out = _PUNCT_TRAIL.sub("", out)
    return out


def is_known(concept: str, kb: dict[str, Any]) -> bool:
    needle = normalize(concept)
    aliases = kb.get("aliases", {}) or {}
    for key, variants in aliases.items():
        if normalize(key) == needle:
            return True
        for v in variants or []:
            if normalize(v) == needle:
                return True
    return False
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_gap_aggregator_alias.py -v
```

- [ ] **Step 5: Commit**

```bash
git add knowledge_gap_aggregator/alias.py tests/test_gap_aggregator_alias.py
git commit -m "feat: alias normalization + KB exact-match"
```

---

### Task 4: Signals — concept universe and per-paper concept extraction (TDD)

This is the part the reviewer flagged. It replaces the old single-array `concepts[]` assumption with a real-schema extractor that walks the eight concept-bearing fields.

**Files:**
- Create: `knowledge_gap_aggregator/signals.py`
- Create: `tests/test_gap_aggregator_signals.py`

- [ ] **Step 1: Tests**

`tests/test_gap_aggregator_signals.py`:

```python
from knowledge_gap_aggregator.signals import (
    SLOT_BY_FIELD,
    concepts_in_paper,
    paper_count_per_concept,
    core_paper_count_per_concept,
)


def _p(arxiv_id, *, importance, **fields):
    base = {
        "arxiv_id": arxiv_id,
        "title": fields.pop("title", ""),
        "topic_tags": [],
        "methods": [],
        "datasets": [],
        "benchmarks": [],
        "baselines": [],
        "metrics": [],
        "mentioned_entities": [],
        "reader_needed_concepts": [],
        "book_usage": {"importance_score_1_to_5": importance},
    }
    base.update(fields)
    return base


def test_slot_by_field_table():
    assert SLOT_BY_FIELD["methods"] == "method"
    assert SLOT_BY_FIELD["datasets"] == "method"
    assert SLOT_BY_FIELD["benchmarks"] == "result"
    assert SLOT_BY_FIELD["baselines"] == "result"
    assert SLOT_BY_FIELD["metrics"] == "result"
    assert SLOT_BY_FIELD["topic_tags"] == "abstract"
    assert SLOT_BY_FIELD["reader_needed_concepts"] == "reader_needed"
    assert SLOT_BY_FIELD["mentioned_entities"] == "mention"


def test_concepts_in_paper_yields_normalized_name_and_slot():
    paper = _p("p1", importance=5,
               title="ViT for Vision",
               methods=["ViT", "Transformer"],
               topic_tags=["computer vision"])
    out = concepts_in_paper(paper)
    # Expect each (normalized_name, slot) pair emitted.
    pairs = sorted((c["normalized"], c["slot"]) for c in out)
    assert ("computer vision", "abstract") in pairs
    assert ("transformer", "method") in pairs
    assert ("vit", "method") in pairs
    # ViT in title → also gets title slot.
    assert ("vit", "title") in pairs


def test_concepts_in_paper_title_match_case_insensitive():
    paper = _p("p1", importance=5, title="A Survey of CLIP",
               methods=["CLIP"])
    out = concepts_in_paper(paper)
    slots = {(c["normalized"], c["slot"]) for c in out}
    assert ("clip", "title") in slots
    assert ("clip", "method") in slots


def test_paper_count_per_concept_from_evidence():
    evidence = {
        "p1": _p("p1", importance=5, methods=["ViT", "Transformer"]),
        "p2": _p("p2", importance=4, methods=["ViT"], baselines=["Transformer"]),
        "p3": _p("p3", importance=2, methods=["wav2vec"]),
    }
    counts = paper_count_per_concept(evidence)
    assert counts["vit"] == 2
    assert counts["transformer"] == 2
    assert counts["wav2vec"] == 1


def test_core_paper_count_uses_book_usage_importance():
    evidence = {
        "p1": _p("p1", importance=5, methods=["ViT"]),
        "p2": _p("p2", importance=3, methods=["ViT"]),  # not core
    }
    counts = core_paper_count_per_concept(evidence, threshold=4)
    assert counts["vit"] == 1
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_gap_aggregator_signals.py -v
```

- [ ] **Step 3: Implement `signals.py` initial functions**

```python
from __future__ import annotations

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


def _importance_score(paper: dict[str, Any]) -> int:
    bu = paper.get("book_usage") or {}
    val = bu.get("importance_score_1_to_5", 0)
    return int(val) if isinstance(val, (int, float)) else 0


def concepts_in_paper(paper: dict[str, Any]) -> list[dict[str, str]]:
    """Walk all concept-bearing fields and emit one entry per (concept, slot).

    The same concept may appear in multiple slots (e.g., methods + title).
    Returned entries: {"raw": ..., "normalized": ..., "slot": ...}
    """
    out: list[dict[str, str]] = []
    title = (paper.get("title") or "").lower()
    for field, slot in SLOT_BY_FIELD.items():
        for raw in paper.get(field, []) or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            norm = normalize(raw)
            if not norm:
                continue
            out.append({"raw": raw, "normalized": norm, "slot": slot})
            # Promote to "title" slot if the concept name appears in the title.
            if norm in title:
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
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_gap_aggregator_signals.py -v
```

- [ ] **Step 5: Commit**

```bash
git add knowledge_gap_aggregator/signals.py tests/test_gap_aggregator_signals.py
git commit -m "feat: signals — concept extraction, paper_count, core_paper_count (real schema)"
```

---

### Task 5: Signals — in_slots & is_method_of_core (TDD)

**Files:**
- Modify: `knowledge_gap_aggregator/signals.py`
- Modify: `tests/test_gap_aggregator_signals.py`

- [ ] **Step 1: Append tests**

```python
from knowledge_gap_aggregator.signals import (
    in_slots_per_concept,
    is_method_of_core_per_concept,
)


def test_in_slots_aggregates_across_papers():
    evidence = {
        "p1": _p("p1", importance=5, title="ViT for Vision",
                 methods=["ViT"], topic_tags=["vision"]),
        "p2": _p("p2", importance=3, baselines=["ViT"]),
    }
    slots = in_slots_per_concept(evidence)
    # ViT appears as method (p1), title (p1), and result via baselines (p2)
    assert sorted(slots["vit"]) == ["method", "result", "title"]
    assert "abstract" in slots["vision"]


def test_is_method_of_core_true_when_methods_of_core_paper():
    evidence = {
        "p1": _p("p1", importance=5, methods=["ViT"]),
        "p2": _p("p2", importance=2, methods=["wav2vec"]),
    }
    out = is_method_of_core_per_concept(evidence, threshold=4)
    assert out.get("vit") is True
    assert out.get("wav2vec") is False  # core threshold not met


def test_is_method_of_core_datasets_also_count():
    evidence = {"p1": _p("p1", importance=5, datasets=["LAION"])}
    out = is_method_of_core_per_concept(evidence, threshold=4)
    assert out.get("laion") is True


def test_is_method_of_core_baselines_do_not_count():
    evidence = {"p1": _p("p1", importance=5, baselines=["GPT-2"])}
    out = is_method_of_core_per_concept(evidence, threshold=4)
    # baselines map to slot "result", not "method of core"
    assert out.get("gpt 2", False) is False
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_gap_aggregator_signals.py -v
```

- [ ] **Step 3: Append implementations**

```python
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
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_gap_aggregator_signals.py -v
```

- [ ] **Step 5: Commit**

```bash
git add knowledge_gap_aggregator/signals.py tests/test_gap_aggregator_signals.py
git commit -m "feat: signals.in_slots + is_method_of_core (evidence-derived)"
```

---

### Task 6: Signals — composite importance score (TDD)

**Files:**
- Modify: `knowledge_gap_aggregator/signals.py`
- Modify: `tests/test_gap_aggregator_signals.py`

- [ ] **Step 1: Append tests**

```python
from knowledge_gap_aggregator.signals import importance, slot_weight


def test_slot_weight_table():
    assert slot_weight(["title"]) == 1.0
    assert slot_weight(["method"]) == 0.8
    assert slot_weight(["result"]) == 0.8
    assert slot_weight(["abstract"]) == 0.6
    assert slot_weight(["reader_needed"]) == 0.4
    assert slot_weight(["mention"]) == 0.2
    assert slot_weight([]) == 0.2


def test_slot_weight_takes_max():
    assert slot_weight(["abstract", "title"]) == 1.0


def test_importance_increases_with_signals():
    low = importance(
        paper_count=1, core_paper_count=0, in_slots=["mention"],
        is_method_of_core=False,
    )
    high = importance(
        paper_count=5, core_paper_count=3, in_slots=["title", "method"],
        is_method_of_core=True,
    )
    assert 0.0 <= low <= 0.30
    assert 0.85 <= high <= 1.0


def test_importance_bounded_0_to_1():
    val = importance(
        paper_count=999, core_paper_count=999, in_slots=["title"],
        is_method_of_core=True,
    )
    assert 0.0 <= val <= 1.0
```

- [ ] **Step 2: Run — expect failure**

```bash
uv run pytest tests/test_gap_aggregator_signals.py -v -k "slot_weight or importance"
```

- [ ] **Step 3: Append implementation**

```python
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
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_gap_aggregator_signals.py -v
```

- [ ] **Step 5: Commit**

```bash
git add knowledge_gap_aggregator/signals.py tests/test_gap_aggregator_signals.py
git commit -m "feat: signals.importance composite (4-signal, no bridge)"
```

---

### Task 7: Aggregator entry — build_digest (TDD)

**Files:**
- Create: `knowledge_gap_aggregator/aggregate.py`
- Modify: `knowledge_gap_aggregator/__init__.py`
- Create: `tests/test_gap_aggregator_digest.py`

- [ ] **Step 1: End-to-end tests**

`tests/test_gap_aggregator_digest.py`:

```python
import json
import shutil
from pathlib import Path

import pytest

from knowledge_gap_aggregator import build_digest

FIXTURE = Path(__file__).parent / "fixtures" / "weak_graph_mini"


@pytest.fixture
def run_dir(tmp_path):
    dest = tmp_path / "run"
    dest.mkdir()
    (dest / "05_weak_graph").mkdir()
    (dest / "04_weak_evidence").mkdir()
    (dest / "06_expansion").mkdir()
    shutil.copy(
        FIXTURE / "weak_global_graph.json",
        dest / "05_weak_graph" / "weak_global_graph.json",
    )
    for f in (FIXTURE / "04_weak_evidence").iterdir():
        shutil.copy(f, dest / "04_weak_evidence" / f.name)
    (dest / "06_expansion" / "known_concepts_snapshot.json").write_text(
        (FIXTURE / "known_concepts_snapshot.json").read_text()
    )
    return dest


def _load_digest(run_dir):
    return json.loads(
        (run_dir / "06_expansion" / "gap_candidates_digest.json").read_text()
    )


def test_build_digest_writes_file(run_dir):
    build_digest(run_dir, run_id="test-run")
    out = run_dir / "06_expansion" / "gap_candidates_digest.json"
    assert out.exists()
    data = _load_digest(run_dir)
    assert data["run_id"] == "test-run"
    assert "candidates" in data
    assert data["params"]["top_n"] == 100
    assert data["params"]["hard_cap"] == 120


def test_build_digest_drops_known_concepts(run_dir):
    build_digest(run_dir, run_id="test-run")
    names = [c["normalized"] for c in _load_digest(run_dir)["candidates"]]
    # "transformer" is in known_concepts_snapshot.aliases
    assert "transformer" not in names


def test_build_digest_includes_real_method(run_dir):
    build_digest(run_dir, run_id="test-run")
    names = [c["normalized"] for c in _load_digest(run_dir)["candidates"]]
    assert "vit" in names
    assert "clip vision encoder" in names


def test_build_digest_respects_hard_cap(tmp_path):
    run = tmp_path / "run"
    (run / "05_weak_graph").mkdir(parents=True)
    (run / "04_weak_evidence").mkdir()
    (run / "06_expansion").mkdir()
    methods = [f"concept_{i}" for i in range(1000)]
    (run / "05_weak_graph" / "weak_global_graph.json").write_text(
        json.dumps({"nodes": [{"id": "p1", "type": "Paper"}], "edges": []})
    )
    (run / "04_weak_evidence" / "p1.json").write_text(json.dumps({
        "arxiv_id": "p1", "title": "", "methods": methods,
        "datasets": [], "benchmarks": [], "baselines": [], "metrics": [],
        "topic_tags": [], "mentioned_entities": [], "reader_needed_concepts": [],
        "book_usage": {"importance_score_1_to_5": 5},
    }))
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text(
        json.dumps({"aliases": {}})
    )
    build_digest(run, run_id="big")
    assert len(_load_digest(run)["candidates"]) <= 120


def test_build_digest_signals_and_evidence_present(run_dir):
    build_digest(run_dir, run_id="test-run")
    c = _load_digest(run_dir)["candidates"][0]
    assert "signals" in c and "importance" in c
    assert "paper_count" in c["signals"]
    assert "is_method_of_core" in c["signals"]
    assert isinstance(c.get("evidence_refs"), list)
    assert isinstance(c.get("graph_neighbors"), list)


def test_build_digest_writes_aggregator_log(run_dir):
    build_digest(run_dir, run_id="test-run")
    log = run_dir / "06_expansion" / "aggregator_log.json"
    assert log.exists()
    data = json.loads(log.read_text())
    assert "dropped" in data
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_gap_aggregator_digest.py -v
```

- [ ] **Step 3: Implement `aggregate.py`**

```python
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
    importance,
    in_slots_per_concept,
    is_method_of_core_per_concept,
    paper_count_per_concept,
)


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


def _display_name_index(evidence: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map normalized -> first observed display (raw) form, preserving casing."""
    seen: dict[str, str] = {}
    for paper in evidence.values():
        for c in concepts_in_paper(paper):
            seen.setdefault(c["normalized"], c["raw"])
    return seen


def _neighbors_from_graph(
    graph: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    limit: int = 5,
) -> dict[str, list[str]]:
    """For each concept (normalized), top-`limit` co-occurring concept displays.

    Co-occurrence: two concepts share at least one paper that mentions both.
    Sourced from evidence (graph not required for v1).
    """
    co: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for paper in evidence.values():
        names_in_paper = {c["normalized"]: c["raw"] for c in concepts_in_paper(paper)}
        keys = list(names_in_paper.keys())
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                co[a][b] += 1
                co[b][a] += 1
    out: dict[str, list[str]] = {}
    display = _display_name_index(evidence)
    for k, neigh in co.items():
        ranked = sorted(neigh.items(), key=lambda x: (-x[1], x[0]))[:limit]
        out[k] = [display.get(n, n) for n, _ in ranked]
    return out


def _evidence_refs_for(
    normalized: str,
    evidence: dict[str, dict[str, Any]],
    *,
    max_refs: int = 2,
    max_chars: int = 200,
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

    pc = paper_count_per_concept(evidence)
    cpc = core_paper_count_per_concept(evidence)
    slots = in_slots_per_concept(evidence)
    imoc = is_method_of_core_per_concept(evidence)
    neighbors = _neighbors_from_graph(graph, evidence)
    display = _display_name_index(evidence)

    all_concepts = sorted(set(pc) | set(slots))

    candidates: list[Candidate] = []
    dropped: list[dict[str, str]] = []

    for norm in all_concepts:
        raw = display.get(norm, norm)
        if is_known(raw, kb) or is_known(norm, kb):
            dropped.append({"concept": raw, "reason": "known"})
            continue
        p = pc.get(norm, 0)
        sl = slots.get(norm, [])
        # Pre-filter: a single mention in only mention/reader_needed-style slots.
        if p <= 1 and set(sl).issubset({"mention", "reader_needed"}):
            dropped.append({"concept": raw, "reason": "too_minor"})
            continue
        sigs = Signals(
            paper_count=p,
            core_paper_count=cpc.get(norm, 0),
            in_slots=sl,
            is_method_of_core=imoc.get(norm, False),
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
            concept=raw,
            normalized=norm,
            importance=imp,
            signals=sigs,
            evidence_refs=_evidence_refs_for(norm, evidence),
            graph_neighbors=neighbors.get(norm, []),
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
        },
        kb_summary={
            "known_count": len(aliases_map),
            "sample_aliases": list(aliases_map.keys())[:10],
        },
        candidates=selected,
    )

    out_path = run_dir / "06_expansion" / "gap_candidates_digest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(digest.to_dict(), indent=2))

    log_path = run_dir / "06_expansion" / "aggregator_log.json"
    log_path.write_text(json.dumps({"dropped": dropped}, indent=2))

    return digest
```

- [ ] **Step 4: Export `build_digest`**

Replace `knowledge_gap_aggregator/__init__.py`:

```python
"""Stage 5 aggregator: turn weak graph + evidence into a bounded digest."""
from knowledge_gap_aggregator.aggregate import build_digest
from knowledge_gap_aggregator.schema import Candidate, Digest, EvidenceRef, Signals

__all__ = ["build_digest", "Candidate", "Digest", "EvidenceRef", "Signals"]
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_gap_aggregator_digest.py -v
```

- [ ] **Step 6: Commit**

```bash
git add knowledge_gap_aggregator/aggregate.py knowledge_gap_aggregator/__init__.py tests/test_gap_aggregator_digest.py
git commit -m "feat: build_digest end-to-end + aggregator_log"
```

---

### Task 8: Wire stage 5a into runner (M0 lands)

**Files:**
- Modify: `scripts/run_auto_research.py`

- [ ] **Step 1: Add import**

Near the top of `scripts/run_auto_research.py`:

```python
from knowledge_gap_aggregator import build_digest
```

- [ ] **Step 2: Insert `run_stage_5_aggregate` above the existing `run_stage_5`**

```python
def run_stage_5_aggregate(run_dir: Path) -> None:
    """Stage 5a (Python): build gap_candidates_digest.json from weak graph + evidence."""
    digest_path = run_dir / "06_expansion" / "gap_candidates_digest.json"
    if digest_path.exists():
        append_run_log(run_dir, "5a", "skipped", "digest already present")
        return
    weak_graph = run_dir / "05_weak_graph" / "weak_global_graph.json"
    if not weak_graph.exists():
        append_run_log(run_dir, "5a", "skipped", "no weak graph yet")
        return
    digest = build_digest(run_dir, run_id=run_dir.name)
    append_run_log(
        run_dir, "5a", "completed",
        f"digest written; candidates={len(digest.candidates)}",
    )
```

- [ ] **Step 3: Modify `run_stage_5` to call aggregate first (old detector still runs)**

Replace `run_stage_5` so its first body line (after the early-return) is `run_stage_5_aggregate(run_dir)`:

```python
def run_stage_5(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "5"):
        append_run_log(run_dir, "5", "skipped", "knowledge gap report already present")
        return
    run_stage_5_aggregate(run_dir)
    spec = ShardSpec(
        stage="5",
        shard_id="knowledge-gaps",
        agent="knowledge_gap_detector",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_gap_detector.toml",
            run_dir.name,
            "5",
            "knowledge-gaps",
            {},
        ),
        expected_outputs=[
            "06_expansion/knowledge_gap_report.json",
            "06_expansion/expansion_need_queue.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor)
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    append_run_log(
        run_dir, "5", "completed", f"knowledge gap report written; queue_items={len(items)}"
    )
```

- [ ] **Step 4: Existing stage-5 test still passes**

```bash
uv run pytest tests/test_auto_research_runner_cli.py::test_run_stage_5_dispatches_gap_detector_and_logs_queue_count -v
```

Expected: PASS (digest write is guarded by `weak_graph.exists()`).

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py
git commit -m "feat: stage 5a (Python aggregator) wired into runner"
```

**M0 ships.**

---

# Milestone M1 — Switch classifier

Wire the new agent. Old detector files **stay on disk** (unused) until M1.5.

---

### Task 9: Classifier skill (SKILL.md)

**Files:**
- Create: `.agents/skills/knowledge-gap-classification/SKILL.md`

- [ ] **Step 1: Write**

```markdown
---
name: knowledge-gap-classification
description: Classify a pre-ranked digest of concept candidates into known / unknown_minor / knowledge_gap and queue the top gaps for expansion.
---

# Knowledge Gap Classification

## Inputs
- `06_expansion/gap_candidates_digest.json` (ranked shortlist, ≤120 entries)
- `06_expansion/known_concepts_snapshot.json` (aliases map only)

You do NOT read `05_weak_graph/weak_global_graph.json` or `04_weak_evidence/*.json`. The digest already summarizes them.

## Outputs
- `06_expansion/extracted_concepts.json` — full classification of every digest candidate
- `06_expansion/knowledge_gap_report.json` — buckets: `known`, `unknown_minor`, `knowledge_gaps`
- `06_expansion/expansion_need_queue.json` — ≤5 items, priority ≥ 0.70

## Rules
- Do NOT re-derive importance — trust the digest `importance` score.
- Every queued concept MUST appear in `candidates[].concept`. No new names.
- `priority` = digest `importance` × confidence multiplier; must be ≥ 0.70 to queue.
- `search_queries` (≥2 per item) derived from `concept` + `graph_neighbors` in the digest entry.
- If fewer than 5 candidates score ≥ 0.70, emit fewer. Never pad.
- `max_papers_to_add` defaults to 3.

## Classification
- `known` — alias-normalized form matches `known_concepts_snapshot.aliases` (rare; aggregator pre-filters most).
- `unknown_minor` — appears in digest but `importance < 0.50`, or only in `mention`/`reader_needed` slots.
- `knowledge_gap` — `importance ≥ 0.50`, ideally with `core_paper_count ≥ 1` or `is_method_of_core = true`.

## Queue schema
```json
{
  "items": [
    {
      "gap_id": "gap_clip_vision_encoder",
      "concept": "CLIP vision encoder",
      "priority": 0.91,
      "needed_for_papers": ["2304.08485"],
      "needed_for_chapters": [],
      "search_queries": ["CLIP vision encoder arxiv", "Contrastive Language Image Pretraining"],
      "target_paper_types": ["foundational method", "survey/background"],
      "max_papers_to_add": 3
    }
  ]
}
```

## Success
- All three report buckets populated.
- Queue ≤5 items, each with ≥2 search_queries and priority ≥ 0.70.
- Every queued `concept` exists in `gap_candidates_digest.json`.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/knowledge-gap-classification/SKILL.md
git commit -m "feat: knowledge-gap-classification SKILL.md"
```

---

### Task 10: Classifier agent toml

**Files:**
- Create: `.codex/agents/knowledge_gap_classifier.toml`

- [ ] **Step 1: Write**

```toml
name = "knowledge_gap_classifier"
description = "Classify pre-ranked digest of concept candidates and queue the top knowledge gaps."
model = "gpt-5.4-mini"
model_reasoning_effort = "low"

developer_instructions = """
Follow .agents/skills/knowledge-gap-classification/SKILL.md.

Inputs: run_id.

Read 06_expansion/gap_candidates_digest.json and the aliases map from
06_expansion/known_concepts_snapshot.json. DO NOT read the weak graph or
weak-evidence files.

Classify every candidate. Write under 06_expansion/:
extracted_concepts.json, knowledge_gap_report.json, expansion_need_queue.json.

Cap: ≤5 queue items, each priority ≥ 0.70. Never pad. Concept names MUST come
from candidates[].concept in the digest.

Return: 'ok: K known, U minor, G gaps, Q queued'.
"""
```

- [ ] **Step 2: Commit**

```bash
git add .codex/agents/knowledge_gap_classifier.toml
git commit -m "feat: knowledge_gap_classifier agent toml"
```

---

### Task 11: SKILL.md prompt-text contract test

**Files:**
- Create: `tests/test_gap_classifier_skill.py`

- [ ] **Step 1: Write test**

```python
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[1]
    / ".agents" / "skills" / "knowledge-gap-classification" / "SKILL.md"
)


def test_skill_exists():
    assert SKILL.exists()


def test_skill_contains_load_bearing_rules():
    text = SKILL.read_text()
    lower = text.lower()
    assert "do not re-derive importance" in lower
    assert "must appear in" in lower
    assert "0.70" in text
    assert "gap_candidates_digest.json" in text


def test_skill_forbids_reading_raw_inputs():
    text = SKILL.read_text()
    assert "05_weak_graph/weak_global_graph.json" in text
    assert "04_weak_evidence/" in text
    assert "DO NOT" in text or "do not read" in text.lower()
```

- [ ] **Step 2: Run — expect PASS**

```bash
uv run pytest tests/test_gap_classifier_skill.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_gap_classifier_skill.py
git commit -m "test: SKILL.md prompt-text contract"
```

---

### Task 12: Refactor stage 5 dispatch + pipeline test (TDD)

**Files:**
- Modify: `scripts/run_auto_research.py`
- Create: `tests/test_stage_5_pipeline.py`

- [ ] **Step 1: Pipeline test (failing)**

```python
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_auto_research import run_stage_5

FIXTURE = Path(__file__).parent / "fixtures" / "weak_graph_mini"


@pytest.fixture
def run_dir(tmp_path):
    dest = tmp_path / "run"
    dest.mkdir()
    for sub in ("05_weak_graph", "04_weak_evidence", "06_expansion"):
        (dest / sub).mkdir()
    shutil.copy(
        FIXTURE / "weak_global_graph.json",
        dest / "05_weak_graph" / "weak_global_graph.json",
    )
    for f in (FIXTURE / "04_weak_evidence").iterdir():
        shutil.copy(f, dest / "04_weak_evidence" / f.name)
    (dest / "06_expansion" / "known_concepts_snapshot.json").write_text(
        (FIXTURE / "known_concepts_snapshot.json").read_text()
    )
    (dest / "run_log.csv").write_text("stage,status,detail\n")
    return dest


def test_run_stage_5_dispatches_classifier(run_dir):
    captured = []

    def fake_run_shards(_run_dir, specs, *, executor):
        captured.extend(specs)
        out = _run_dir / "06_expansion"
        (out / "knowledge_gap_report.json").write_text(
            json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": []})
        )
        (out / "expansion_need_queue.json").write_text(
            json.dumps({"items": []})
        )
        (out / "extracted_concepts.json").write_text(json.dumps([]))

    with patch("scripts.run_auto_research.run_shards", side_effect=fake_run_shards):
        run_stage_5(run_dir)

    assert (run_dir / "06_expansion" / "gap_candidates_digest.json").exists()
    assert len(captured) == 1
    assert captured[0].agent == "knowledge_gap_classifier"


def test_run_stage_5_idempotent_when_report_present(run_dir):
    (run_dir / "06_expansion" / "knowledge_gap_report.json").write_text(
        json.dumps({"known": [], "unknown_minor": [], "knowledge_gaps": []})
    )
    with patch("scripts.run_auto_research.run_shards") as m:
        run_stage_5(run_dir)
        m.assert_not_called()
```

- [ ] **Step 2: Run — expect failure (agent still named knowledge_gap_detector)**

```bash
uv run pytest tests/test_stage_5_pipeline.py -v
```

- [ ] **Step 3: Update `run_stage_5` to dispatch classifier**

Replace the body of `run_stage_5`:

```python
def run_stage_5(run_dir: Path, *, executor: str = DEFAULT_EXECUTOR) -> None:
    if primary_artifact_exists(run_dir, "5"):
        append_run_log(run_dir, "5", "skipped", "knowledge gap report already present")
        return
    run_stage_5_aggregate(run_dir)
    spec = ShardSpec(
        stage="5",
        shard_id="knowledge-gaps",
        agent="knowledge_gap_classifier",
        model="gpt-5.4-mini",
        prompt=_generic_agent_prompt(
            ".codex/agents/knowledge_gap_classifier.toml",
            run_dir.name,
            "5",
            "knowledge-gaps",
            {},
        ),
        expected_outputs=[
            "06_expansion/knowledge_gap_report.json",
            "06_expansion/expansion_need_queue.json",
        ],
    )
    run_shards(run_dir, [spec], executor=executor)
    queue = _load_json(run_dir / "06_expansion" / "expansion_need_queue.json")
    items = queue.get("items", []) if isinstance(queue, dict) else []
    append_run_log(
        run_dir, "5", "completed", f"knowledge gap report written; queue_items={len(items)}"
    )
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_stage_5_pipeline.py -v
```

- [ ] **Step 5: Run the existing CLI test (still uses old name) — expect FAILURE**

```bash
uv run pytest tests/test_auto_research_runner_cli.py::test_run_stage_5_dispatches_gap_detector_and_logs_queue_count -v
```

This is expected. It will be fixed in M2 (Task 15).

- [ ] **Step 6: Commit**

```bash
git add scripts/run_auto_research.py tests/test_stage_5_pipeline.py
git commit -m "feat: stage 5 dispatches knowledge_gap_classifier (digest-only)"
```

**M1 ships. Stage 5 is now context-bounded.** Old `knowledge_gap_detector.toml` and `.agents/skills/knowledge-gap-detection/` remain on disk, unused — for safe rollback.

---

# Milestone M1.5 — Regression gate + detector deletion

Manual validation on the existing run, then remove the old files.

---

### Task 13: Regression run on existing data

**Files:** (none modified — manual command + observation)

- [ ] **Step 1: Run aggregator against existing run**

```bash
cd /home/nguyen/code/swarn_auto_research
uv run python -c "
from pathlib import Path
from knowledge_gap_aggregator import build_digest
d = build_digest(
  Path('research_runs/ai-agent-system-in-coding-that-can-accelerate-my-working-process-20260515-152516'),
  run_id='regression',
)
print(f'candidates={len(d.candidates)}')
for c in d.candidates[:15]:
  print(f'  {c.importance:.2f}  {c.concept}')
"
```

- [ ] **Step 2: Diff against old queue**

```bash
cat research_runs/ai-agent-system-in-coding-that-can-accelerate-my-working-process-20260515-152516/06_expansion/expansion_need_queue.json | python -m json.tool
```

Compare: every concept in the old queue (≤5 items) should appear somewhere in the new digest's top 20. If one is missing **and** it's clearly important (subjective check by the author), tune weights in `signals.py` and re-run. If the digest looks reasonable, proceed.

- [ ] **Step 3: Inspect digest file size**

```bash
du -h research_runs/ai-agent-system-in-coding-that-can-accelerate-my-working-process-20260515-152516/06_expansion/gap_candidates_digest.json
```

Expected: ≤ ~80 KB. If much larger, investigate — likely a bug in `hard_cap` enforcement.

- [ ] **Step 4: Author records sign-off**

Add a one-line note to `06_expansion/aggregator_regression.md` in the existing run dir:

```
Regression check 2026-05-16: digest top-20 covers old queue. OK to delete detector.
```

`git add` + commit.

```bash
git add research_runs/ai-agent-system-in-coding-that-can-accelerate-my-working-process-20260515-152516/06_expansion/aggregator_regression.md
git commit -m "chore: regression note for stage 5 aggregator"
```

If regression is **not** clean, stop here. Do not proceed to Task 14. Tune weights and re-run Task 13 from Step 1.

---

### Task 14: Delete the old detector files

**Files:**
- Delete: `.codex/agents/knowledge_gap_detector.toml`
- Delete: `.agents/skills/knowledge-gap-detection/`

- [ ] **Step 1: Remove**

```bash
git rm .codex/agents/knowledge_gap_detector.toml
git rm -r .agents/skills/knowledge-gap-detection/
```

- [ ] **Step 2: Tests will fail — expected**

```bash
uv run pytest tests/ -v
```

`test_codex_scaffold.py` and `test_auto_research_runner_cli.py` (old dispatch test) will fail. Handled in M2.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: remove knowledge_gap_detector (regression passed)"
```

**M1.5 ships.**

---

# Milestone M2 — Test + doc cleanup

---

### Task 15: Update orchestrator skill doc

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`

- [ ] **Step 1: Replace line 158**

Replace:

> Dispatch `knowledge_gap_detector`. Skip Stage 6 only if `expansion_need_queue.json.items` is empty.

with:

> Stage 5 runs the Python aggregator (`knowledge_gap_aggregator.build_digest`) to write `06_expansion/gap_candidates_digest.json`, then dispatches `knowledge_gap_classifier` which reads only the digest. Skip Stage 6 only if `expansion_need_queue.json.items` is empty.

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "docs: orchestrator references knowledge_gap_classifier"
```

---

### Task 16: Update test_codex_scaffold.py expected sets

**Files:**
- Modify: `tests/test_codex_scaffold.py`

- [ ] **Step 1: Replace strings**

In `EXPECTED_AGENTS`: replace `"knowledge_gap_detector"` with `"knowledge_gap_classifier"`.

In `EXPECTED_SKILLS`: replace `"knowledge-gap-detection"` with `"knowledge-gap-classification"`.

- [ ] **Step 2: Run — expect PASS**

```bash
uv run pytest tests/test_codex_scaffold.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_codex_scaffold.py
git commit -m "test: codex scaffold expects classifier"
```

---

### Task 17: Rename CLI stage-5 dispatch test

**Files:**
- Modify: `tests/test_auto_research_runner_cli.py`

- [ ] **Step 1: Replace identifiers**

Find:

```python
def test_run_stage_5_dispatches_gap_detector_and_logs_queue_count(tmp_path, monkeypatch):
```

Replace with:

```python
def test_run_stage_5_dispatches_classifier_and_logs_queue_count(tmp_path, monkeypatch):
```

Find:

```python
    assert captured[0].agent == "knowledge_gap_detector"
```

Replace with:

```python
    assert captured[0].agent == "knowledge_gap_classifier"
```

- [ ] **Step 2: Run the test — expect PASS**

```bash
uv run pytest tests/test_auto_research_runner_cli.py::test_run_stage_5_dispatches_classifier_and_logs_queue_count -v
```

- [ ] **Step 3: Run full suite — expect ALL PASS**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_auto_research_runner_cli.py
git commit -m "test: stage 5 cli test asserts classifier dispatch"
```

**M2 ships.**

---

## Final verification

- [ ] `uv run pytest tests/ -v` — all green.
- [ ] `du -h research_runs/<run>/06_expansion/gap_candidates_digest.json` ≤ ~80 KB.
- [ ] Old `knowledge_gap_detector.toml` and `knowledge-gap-detection/` removed.
- [ ] Orchestrator skill mentions classifier + aggregator.
- [ ] No `networkx` import anywhere in `knowledge_gap_aggregator/`.
