---
name: knowledge-gap-classification
description: Classify a pre-ranked digest of concept candidates into known / unknown_minor / knowledge_gap and queue the top gaps for expansion.
---

# Knowledge Gap Classification

## Inputs
- `06_expansion/gap_candidates_digest.json` (ranked shortlist, ≤180 entries)
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
