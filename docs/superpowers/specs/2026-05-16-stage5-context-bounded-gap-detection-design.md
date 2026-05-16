# Stage 5 — Context-Bounded Knowledge Gap Detection — Design Spec

**Date:** 2026-05-16
**Author:** brainstorming session (Claude + user)
**Status:** Approved, revised post expert review (rev 3)

## Revision history

- **rev 3 (2026-05-16, post 2nd expert review):**
  - Aggregator now actually reads `weak_global_graph.json` — candidate universe = evidence concepts ∪ non-paper graph nodes; new `graph_paper_count`/`graph_neighbors`/`is_method_of_core_via_graph` signals; `paper_count` is the union of evidence and graph paper sources.
  - Fixture edge types corrected against the real weak-graph schema (`INTRODUCES`, `USES`, `USES_DATASET`, `EVALUATES_ON`, …; no `PROPOSES`).
  - Title matching is word-boundary (tokenized), not naive substring.
  - Automated digest size guard: `build_digest` raises if serialized JSON > 100 KB; test fixture verifies the cap.
  - Regression check (M1.5) widened to four dimensions: old-queue coverage, `reader_needed_concepts` sample, core-paper `methods` sample, high-degree graph nodes.

- **rev 2 (2026-05-16, post expert review):**
  - Real `04_weak_evidence/*.json` schema documented (concepts in `methods`/`benchmarks`/`datasets`/`baselines`/`mentioned_entities`/`reader_needed_concepts`; importance in `book_usage.importance_score_1_to_5`). Original fixture/signal design assumed a `concepts[]` array with `slot` — corrected.
  - `bridge_score` and `networkx` dependency dropped. Four remaining signals cover the SKILL.md heuristics. May add later if regression shows missed gaps.
  - `top_n` raised 40 → 100 (hard cap 120) to reduce the chance of the digest dropping a real gap; size remains bounded (~60 KB).
  - Deletion of the old `knowledge_gap_detector` gated behind a regression check on an existing run (new milestone M1.5).
  - `is_method_of_core` now derived from evidence (`methods` field of a core paper) rather than graph edges; weak graph read only for `graph_neighbors`.

## Goal

Replace the single agent that currently reads the entire weak global graph + every weak-evidence file + the KB snapshot to pick ≤5 knowledge gaps. Move the heavy reading into deterministic Python, and let the LLM classify a small, bounded shortlist. Make stage 5 safe from LLM context-window overflow regardless of how large the corpus grows.

## Problem

`run_stage_5` dispatches one agent (`knowledge_gap_detector`) that reads:
- `06_expansion/known_concepts_snapshot.json`
- All ~264 `04_weak_evidence/*.json` files
- The full `05_weak_graph/weak_global_graph.json` — currently 1.6 MB, 5,428 nodes, 5,813 edges

…and emits ≤5 queue items. The agent ingests megabytes of structured data to produce kilobytes of judgment. As corpora grow, this hits the LLM context limit and can corrupt the run. Quality also degrades long before the hard limit because the model skims.

## Non-Goals (v1)

- Per-community gap detection (different feature; would change queue semantics).
- Incremental re-aggregation when papers are added (full re-run is fast enough; defer until perf demands it).
- Replacing `knowledge_base_reader` (stage 4) — it produces a small artifact and is not on the overflow path.

## Decisions Locked in Brainstorming

| Decision | Choice |
|---|---|
| Approach | **A — Python pre-aggregation + tiny classifier agent** (over map-reduce or two-pass funnel) |
| LLM input cap | Bounded digest (~25–30 KB) of top-N candidates, independent of corpus size |
| `top_n` candidates | 100 (hard cap 120 with core-paper safety-net) |
| Agent name | Rename `knowledge_gap_detector` → `knowledge_gap_classifier` (new contract) |
| Stage number | Stay on stage 5 (5a Python + 5b agent); preserve `primary_artifact_exists("5")` semantics |
| Community detection | **Dropped from v1.** No `bridge_score`, no `networkx`. Revisit only if regression shows missed gaps. |
| Sharding | None — one agent call per run, single `ShardSpec` |
| Reasoning effort | `medium` → `low` (task is now small) |
| Old detector removal | Gated on regression check (M1.5) — not deleted in M1 |

## Architecture

```
swarn_auto_research/
├── knowledge_gap_aggregator/             # NEW module
│   ├── __init__.py
│   ├── aggregate.py                      # entry: build digest from graph + evidence + KB
│   ├── signals.py                        # importance signal functions (pure, unit-testable)
│   ├── alias.py                          # alias-normalization + KB exact-match filter
│   └── schema.py                         # dataclasses for digest entries
├── scripts/
│   └── run_auto_research.py              # run_stage_5 = run_stage_5_aggregate + run_stage_5_classify
├── .codex/agents/
│   └── knowledge_gap_classifier.toml     # NEW (replaces knowledge_gap_detector.toml)
└── .agents/skills/
    └── knowledge-gap-classification/     # NEW (replaces knowledge-gap-detection/)
        └── SKILL.md
```

Module boundaries:
- `knowledge_gap_aggregator/` is the only module that reads the full weak graph and evidence files. Nothing else changes.
- The agent reads only the digest + KB snapshot.

## Stage 5 Sub-Stages

| Sub-stage | Layer | Reads | Writes |
|---|---|---|---|
| 5a aggregate | Python (in-process) | `weak_global_graph.json`, `04_weak_evidence/*.json`, `known_concepts_snapshot.json` | `06_expansion/gap_candidates_digest.json`, `06_expansion/aggregator_log.json` |
| 5b classify | One agent (`knowledge_gap_classifier`) | `gap_candidates_digest.json`, `known_concepts_snapshot.json` aliases | `06_expansion/extracted_concepts.json`, `06_expansion/knowledge_gap_report.json`, `06_expansion/expansion_need_queue.json` |

`run_stage_5` completes only when both finish. `primary_artifact_exists("5")` continues to key on `knowledge_gap_report.json` — backward-compatible.

## Digest Schema

**File:** `06_expansion/gap_candidates_digest.json`

```json
{
  "run_id": "...",
  "generated_at": "2026-05-16T...",
  "params": {
    "top_n": 40,
    "hard_cap": 50,
    "min_importance_score": 0.30,
    "kb_alias_normalized": true
  },
  "kb_summary": {
    "known_count": 312,
    "sample_aliases": ["transformer", "attention", "..."]
  },
  "candidates": [
    {
      "concept": "CLIP vision encoder",
      "normalized": "clip vision encoder",
      "importance": 0.87,
      "signals": {
        "paper_count": 4,
        "core_paper_count": 2,
        "in_slots": ["title", "method", "result"],
        "is_method_of_core": true,
        "bridge_score": 0.71,
        "alias_hit": false
      },
      "evidence_refs": [
        {"arxiv_id": "2304.08485", "slot": "method", "snippet": "uses CLIP vision encoder ViT-L/14 as image tower"},
        {"arxiv_id": "2310.03744", "slot": "title", "snippet": "..."}
      ],
      "graph_neighbors": ["ViT", "image tower", "LLaVA"]
    }
  ]
}
```

**Size budget:** ≤120 entries × ~600 bytes ≈ ≤72 KB. Still independent of corpus size and well under a single-call context.

## Real `04_weak_evidence/*.json` schema (rev 2)

Concept-bearing fields (all are flat string lists unless noted):

| Field | Slot derived | Notes |
|---|---|---|
| `methods` | `method` | central to the paper |
| `datasets` | `method` | training/eval data — same weight as methods |
| `benchmarks` | `result` | evaluation set |
| `baselines` | `result` | compared-against |
| `metrics` | `result` | reporting metric — usually mention-weight |
| `mentioned_entities` | `mention` | low weight |
| `reader_needed_concepts` | `reader_needed` | concepts the reader must already know |
| `topic_tags` | `abstract` | high-level grouping |
| `title` | `title` | string; concept gets `title` slot if it appears as a substring (case-insensitive) |

Importance is at `book_usage.importance_score_1_to_5` (integer 1–5).

The **concept universe** for a run is the union of all concept-bearing fields across all `04_weak_evidence/*.json`, normalized via `alias.normalize`. The weak graph is read only for `graph_neighbors` (concepts co-occurring with the target via paper-concept edges).

## Importance Scoring (deterministic, rev 2)

In `signals.py`:

```
importance = (
    0.35 * normalize(core_paper_count, cap=3)
  + 0.25 * normalize(paper_count, cap=5)
  + 0.25 * slot_weight                      # title=1.0, method/result=0.8, abstract=0.6, reader_needed=0.4, mention/other=0.2
  + 0.15 * (1.0 if is_method_of_core else 0.0)
)
```

`normalize(x, cap)` = `min(x, cap) / cap`. Weights renormalized after dropping `bridge_score`.

Signals (all derived from `04_weak_evidence`, except the optional graph lookup):

- **`paper_count`** — distinct papers (arxiv_ids) where the concept appears in any concept-bearing field.
- **`core_paper_count`** — same, restricted to papers with `book_usage.importance_score_1_to_5 ≥ 4`.
- **`in_slots`** — set of slot labels derived from which field(s) the concept appeared in, across all papers (plus `title` if matched against the paper's title string).
- **`is_method_of_core`** — concept appears in the `methods` (or `datasets`) field of at least one core paper.
- **`graph_neighbors`** — top-5 co-occurring concept display names from the weak graph (concepts that share at least one paper-edge with the target).

## Pre-Filter (never sent to the agent)

A concept is dropped at the Python layer before scoring if any of:
- alias-normalized form exact-matches an entry in `known_concepts_snapshot.aliases` → `known`
- single mention in a non-core paper with slot ∈ {`reference`, `related_work`} → too minor

Every dropped concept and the reason are logged to `06_expansion/aggregator_log.json` for inspection. The agent never sees these.

## Candidate Selection

1. Compute `importance` for every concept that passes the pre-filter.
2. Sort descending.
3. Keep top-100 by score.
4. Safety-net: additionally include any concept with `core_paper_count ≥ 2` not already in top-100.
5. Hard cap at 120 entries.
6. For each survivor, pull at most 2 evidence snippets (≤200 chars each — drawn from the paper's `solution`/`problem` arrays, falling back to the concept name itself) and the top-5 graph neighbors.

## Classifier Agent Contract

**Agent:** `knowledge_gap_classifier`
**Model:** `gpt-5.4-mini`
**Reasoning effort:** `low`

**Reads:**
- `06_expansion/gap_candidates_digest.json`
- `06_expansion/known_concepts_snapshot.json` (aliases map only)

**Does NOT read:** weak global graph; weak-evidence files; full KB.

**SKILL.md hard rules:**
- Do NOT re-derive importance — trust the digest score.
- Every queued concept MUST appear in `candidates[].concept`. No new names.
- `priority` = digest `importance` × confidence multiplier (≥ 0.70 required to queue).
- `search_queries` derived from `concept` + `graph_neighbors`.
- If fewer than 5 candidates score ≥ 0.70, emit fewer. Never pad.
- Emit ≥ 2 `search_queries` per queue item.

**Outputs (unchanged schemas, downstream-compatible):**
- `06_expansion/extracted_concepts.json` — full classification (`known` / `unknown_minor` / `knowledge_gap`)
- `06_expansion/knowledge_gap_report.json` — three buckets
- `06_expansion/expansion_need_queue.json` — ≤ 5 items

## Testing

New files under `tests/`:

```
tests/
├── test_gap_aggregator_signals.py        # per-signal unit tests on tiny fixture
├── test_gap_aggregator_alias.py          # alias-normalize + KB exact-match edge cases
├── test_gap_aggregator_digest.py         # end-to-end aggregator: fixture in -> digest out
├── test_gap_classifier_skill.py          # prompt-text contract for SKILL.md
├── test_gap_classifier_contract.py       # JSON schema validation on classifier output (mocked SDK)
└── test_stage_5_pipeline.py              # stage_5 runner with classifier mocked at dispatch seam
```

**Fixture:** `tests/fixtures/weak_graph_mini/` — 10 papers, 30 concepts, 50 edges, 3 communities.

**Key assertions:**
- Each signal function is a pure function and unit-tested with hand-rolled inputs.
- Digest size: `len(candidates) ≤ 50` on a 1,000-concept synthetic input.
- Alias filter: a concept matching `known_concepts_snapshot.aliases` is never in the digest.
- SKILL.md contains the load-bearing rule strings ("Do NOT re-derive importance", "must appear in the digest", "≥ 0.70 priority").
- Pipeline test: with classifier mocked, `expansion_need_queue.json` is written and readable by `load_expansion_gap_items`.
- Backward-compat: `primary_artifact_exists("5")` still passes off `knowledge_gap_report.json`.

**No real Codex calls in tests** — mock at the `dispatch.run_shards` seam (existing pattern). Target: full `pytest tests/` stays under 30s.

## Rollout

Three independently shippable milestones:

| Milestone | Scope |
|---|---|
| **M0 — aggregator only** | Ship `knowledge_gap_aggregator/`; write `gap_candidates_digest.json` to disk. Old agent untouched. Side-by-side observable run. |
| **M1 — switch classifier** | Wire `knowledge_gap_classifier` reading only the digest. `knowledge_gap_detector` files remain on disk (unused). Stage 5 becomes context-bounded. |
| **M1.5 — regression gate** | Run new stage 5 on existing `ai-agent-system-...-152516`. Diff new queue vs. old queue. Only after sign-off, delete the old detector skill + toml. |
| **M2 — cleanup** | Update `auto-research-orchestrator/SKILL.md`; refresh `test_codex_scaffold.py` expected agent set; refresh `test_auto_research_runner_*` mocks; drop dead code in `run_auto_research.py`. |

**Regression check (manual, one-shot before M1 merge):** run new stage 5 against the existing `ai-agent-system-...-152516` run. Compare the new digest's top-10 against the old queue. Overlap expected; non-identity acceptable. Missing-but-clearly-important concepts → tune weights, not the agent.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Deterministic score misses a gap an LLM would have caught | top_n=100 (cap 120) is generous; core-paper safety-net; regression check M1.5 before deletion; weights centralized in `signals.py` and tunable |
| Alias normalization too aggressive (drops a real gap as known) | Unit tests on plurals/hyphens/acronyms; every pre-filter drop logged to `aggregator_log.json` for inspection |
| Downstream consumers depend on old `extracted_concepts.json` shape | Verified: stage 6 only reads `expansion_need_queue.json`; schema unchanged |
| Slot derivation from real schema is lossy (fields don't map 1:1 to slots) | Hand-tuned mapping table in `signals.SLOT_BY_FIELD`; unit-tested with fixtures derived from a real evidence file |

## Open Questions

None at design approval time. Implementation plan will surface lower-level details (exact networkx call signature, evidence-snippet selection rule, fixture content).

## Next Step

Invoke `writing-plans` to produce the implementation plan covering milestones M0–M2 with concrete tasks, file diffs, and contract tests.
