---
name: knowledge-gap-detection
description: Classify required concepts vs user-known concepts and queue the most important gaps for expansion.
---

# Knowledge Gap Detection

## Inputs
- `06_expansion/known_concepts_snapshot.json` (uses its `aliases` map)
- `04_weak_evidence/*.json`
- `05_weak_graph/weak_global_graph.json`

## Outputs
- `06_expansion/extracted_concepts.json`
- `06_expansion/knowledge_gap_report.json` (buckets: `known`, `unknown_minor`, `knowledge_gaps`)
- `06_expansion/expansion_need_queue.json`

## Classification (per concept from `reader_needed_concepts` ∪ graph nodes)
- `known` — matches snapshot or alias (normalized form).
- `unknown_minor` — passing mention, dataset/benchmark with no central role, or one-sentence explainable.
- `knowledge_gap` — unknown AND important AND would confuse the reader.

## Importance signals
- appears in a core paper (importance_score ≥ 4)
- title / abstract / solution / result / methods slot
- mentioned by ≥ 2 papers
- method/dataset/benchmark/baseline of a core paper
- bridges multiple graph communities

## Caps
- ≤ 5 queue items (MVP). Each has `search_queries` (≥ 2) and `max_papers_to_add` (default 3).

## Queue schema
```json
{
  "items": [
    {
      "gap_id": "gap_clip_vision_encoder",
      "concept": "CLIP vision encoder",
      "priority": 0.91,
      "needed_for_papers": ["2304.08485"],
      "needed_for_chapters": ["..."],
      "search_queries": ["CLIP vision encoder arxiv", "Contrastive Language Image Pretraining"],
      "target_paper_types": ["foundational method", "survey/background"],
      "max_papers_to_add": 3
    }
  ]
}
```

## Success
- All three report buckets populated.
- Queue ≤ 5 items, each with ≥ 2 `search_queries`.
