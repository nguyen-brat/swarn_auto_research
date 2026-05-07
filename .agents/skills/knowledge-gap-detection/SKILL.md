---
name: knowledge-gap-detection
description: Compare paper-required concepts against the user's known concepts and emit a knowledge_gap_report.
---

# Knowledge Gap Detection

## Goal
Decide which unknown concepts are important enough to drive paper-pool expansion.

## Inputs
- `06_expansion/known_concepts_snapshot.json`
- `04_weak_evidence/*.json`
- `05_weak_graph/weak_global_graph.json`

## Outputs
- `06_expansion/extracted_concepts.json`
- `06_expansion/knowledge_gap_report.json`
- `06_expansion/expansion_need_queue.json`

## Rules
- Concept matching uses the normalized form. Use the `aliases` map in `known_concepts_snapshot.json`.
- For every concept extracted from `reader_needed_concepts` and graph nodes, classify as one of:
  - `known` — matches a known concept or alias.
  - `unknown_minor` — unknown but only mentioned in passing, dataset/benchmark name with no central role, or trivially explainable in one sentence.
  - `knowledge_gap` — unknown AND important AND its absence would confuse the reader.
- Compute `importance` per concept based on:
  - appears in core paper (importance_score_1_to_5 ≥ 4)
  - appears in title/abstract/solution/result/methods
  - mentioned by ≥ 2 papers
  - is a method/dataset/benchmark/baseline used by a core paper
  - bridges multiple graph communities
- Hard cap: pick the top 5 knowledge gaps for the expansion queue regardless of how many qualify (MVP budget).
- Every queue item must include search queries and `max_papers_to_add` (default 3).

## Output schema for `expansion_need_queue.json`
```json
{
  "items": [
    {
      "gap_id": "gap_clip_vision_encoder",
      "concept": "CLIP vision encoder",
      "priority": 0.91,
      "needed_for_papers": ["2304.08485"],
      "needed_for_chapters": ["Large Multimodal Model Architecture"],
      "search_queries": [
        "CLIP vision encoder arxiv",
        "Contrastive Language Image Pretraining CLIP paper"
      ],
      "target_paper_types": ["foundational method", "survey/background"],
      "max_papers_to_add": 3
    }
  ]
}
```

## Success check
- `knowledge_gap_report.json` has three buckets: `known`, `unknown_minor`, `knowledge_gaps`.
- `expansion_need_queue.json.items` length ≤ 5.
- Every queue item has `search_queries` (≥ 2) and `max_papers_to_add` ≤ 3.
