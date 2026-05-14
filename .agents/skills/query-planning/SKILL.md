---
name: query-planning
description: Expand a single topic into 4–8 distinct aspects with per-aspect queries and keywords, so Stage 1 search covers the whole topic instead of one popular angle.
---

# Query Planning

## Goal
Produce a search plan that covers the topic from multiple distinct angles. The plan drives Stage 1; missing an aspect here means missing every paper that lives in it.

## Input
- `topic` (string)
- optional user-supplied queries / keywords (orchestrator passes these through; merge into the most relevant aspect)

## Output
- `00_input/search_plan.json`
- Do not include `target_seed_papers`; Stage 1 keeps every paper returned by the bulk search relevance gates.

## Aspect coverage (think across these axes; emit 4–6 total)
- **Method families** — the major algorithmic approaches that solve the topic (e.g. for long-context: sparse attention, linear/state-space attention, KV-cache compression, retrieval-augmented context, memory-augmented attention).
- **Architectural enablers** — positional encoding tricks, kernel design, fused ops.
- **Training and adaptation** — long-context fine-tuning, continued pretraining, distillation.
- **Evaluation** — benchmarks, probing tasks, robustness measures.
- **Foundational priors** — the canonical predecessor papers a reader needs (Transformer, FlashAttention, etc.) — only when central to the topic.
- **Boundary aspects** — adjacent areas the topic borrows from (e.g. retrieval, RAG) when they're load-bearing.

Skip axes that don't apply. Aim for 4 aspects on a narrow topic, up to 6 on a broad one. Aspects must be distinct — if two would share most queries, merge them.

## Per-aspect rules
- `aspect_id`: short snake_case slug.
- `title`: human-readable.
- `rationale`: 1 sentence — why this aspect matters and what would be missed without it.
- `normal_queries`: 2–3 queries Semantic Scholar / HF search would understand. Mix specific terms with broader phrases.
- `survey_queries`: 1 query that biases toward survey/review papers (start with "survey", "review", "overview").
- `positive_keywords`: 3–5 keywords. A kept paper must mention at least one (across the union). Use distinctive vocabulary, not generic words.
- `negative_keywords`: aspect-specific exclusions (rarely needed; usually leave empty and rely on global).

## Hard total budget (load-bearing for runtime)
Each Stage 1 query triggers ~5 Semantic Scholar calls with citation traversal — query count drives runtime linearly. Keep totals at:
- **≤ 15 normal queries** across all aspects combined.
- **≤ 6 survey queries** across all aspects combined.
- If your aspect breakdown would exceed these, **merge similar aspects** or drop a query — do NOT silently push past the cap.

## Global keywords
- `global_negative_keywords`: 3–8 entries that exclude noise across all aspects (e.g. "image classification only", "speech only", "GNN").

## Hard rules
- Every query must be a string the search tools accept (no operators, no quotes — plain phrases).
- Every keyword in lowercase except proper nouns / model names.
- No aspect overlaps another aspect's `aspect_id`, `title`, or > 50% of its normal_queries.
- If the user supplied any queries/keywords, include them verbatim in the most relevant aspect (do not drop them).
- Never invent papers, methods, or numerical claims.

## Output schema
```json
{
  "topic": "Long-context attention methods for large language models",
  "aspects": [
    {
      "aspect_id": "sparse_attention",
      "title": "Sparse attention methods",
      "rationale": "Sparse patterns are the dominant strategy for long-context efficiency; missing this aspect would drop most of the recent work.",
      "normal_queries": [
        "sparse attention long context transformer",
        "block-sparse attention LLM",
        "selected-token attention efficient inference"
      ],
      "survey_queries": ["survey efficient long-context attention"],
      "positive_keywords": ["sparse attention", "block-sparse", "selected tokens", "top-k attention"],
      "negative_keywords": []
    }
  ],
  "global_negative_keywords": ["image classification only", "speech only", "graph neural network"]
}
```

## Success
- 4–6 aspects, all with non-empty `normal_queries` and `positive_keywords`.
- Total normal_queries ≤ 15; total survey_queries ≤ 6.
- No two aspects have the same `aspect_id`.
- User-supplied queries/keywords are preserved.
- File parses as valid JSON.
