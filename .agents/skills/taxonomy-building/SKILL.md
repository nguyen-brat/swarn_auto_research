---
name: taxonomy-building
description: Three-tier handbook outline — 8 fixed book sections, one family per community, one method per verified full-text paper.
---

# Taxonomy Building

## Inputs
- `11_verified_graph/global_graph.json` (fall back to `05_weak_graph/weak_global_graph.json`)
- `06_expansion/known_concepts_snapshot.json`, `knowledge_gap_report.json`
- Stage 12 payload `verified_full_text_arxiv_ids` plus Stage 8/9/10 availability artifacts
- `10_verified_evidence/*.json` (titles, methods, neighbors)
- `04_weak_evidence/*.json` (paper_type, importance_score)
- `00_input/topic.md`

## Outputs
- `12_taxonomy/communities.json` — raw clustering
- `12_taxonomy/taxonomy.json` — labeled communities
- `12_taxonomy/outline.json` — three-tier outline

## Family clustering
- Greedy from highest-degree non-paper node; attach connected nodes by strongest tie; stop at threshold.
- Family must contain ≥ 1 verified full-text promoted paper. Drop background-only communities.
- **No upper cap** on families — Book_style requires one chapter per family.
- Family title = central Method/Concept node (or dominant Method node if Paper-centric).
- Family titles must be short method-family labels, not paper titles, benchmark results, or full claims.
- Reject labels that contain sentence punctuation, reported numbers/results, benchmark-result wording, implementation-environment details, model-size/configuration details, or phrases like "reports", "achieves", "outperforms", "evaluation", "speedup", "trained with", or "uses N".
- Merge duplicate normalized family titles before writing `outline.json`; e.g. two `full attention` communities become one family with combined `method_ids`.
- For singleton fallback communities, choose the nearest clean bucket from graph concepts. Use domain-neutral buckets first: algorithmic method, model architecture, training/adaptation, inference/runtime optimization, memory/compression, retrieval/tooling, evaluation/benchmarking, data/task/application, or theory/analysis. If the topic has a clearer domain-specific family name, use that instead.

## Parts (topic-adaptive grouping)
After clustering, assign every family to exactly one part.

Default labels (Book_style.md): `interpretable`, `local`, `global`, `model_specific`, `evaluation_outlook`. You MAY rename, merge, or drop default parts when the topic fits a different shape.

Hard rules (self-validate):
- 2 ≤ len(parts) ≤ 5
- Every family appears in exactly one part
- Every part contains ≥ 1 family

Emit as `parts: [{id, title, family_ids[]}]` in `outline.json`.

## Singleton handling
If clustering produces a singleton family (`len(method_ids) == 1`), prefer to merge it into the nearest non-singleton family only when shared verified-graph edges provide strong evidence. The deterministic Stage 12.5 post-processor `merge_singletons` in `swarn_research_mcp.research_book` will normalize the outline before Stage 13; if no strong merge evidence exists, the method stays as a standalone method chapter under the `standalone` group. Do not create catch-all `other_*` families.

## Methods
- One per Stage 12 payload `verified_full_text_arxiv_ids` entry, and no methods outside that exact list.
- `method_id` = slug of `verified_evidence.methods[0].name`; if no method is verified, slug the paper title. Never use a raw arXiv ID as `method_id`.
- `family_id` = community containing the arxiv_id; if multiple, pick largest by `(#promoted × #verified_edges)`.
- `neighbor_method_ids`: up to 5 closest by shared verified-graph edges, across all families.
- Method IDs must name a method/system, not a paper section or raw arXiv ID. Reject IDs that are raw arXiv IDs, start with section numbers, or contain labels like `problem-formulation`, `prefilling-stage`, `observation-window`, or `pre-filling`; fall back to a slug from the paper title.

## Book sections (fixed, always emitted)
`preface`, `motivating_intro`, `core_concepts`, `goals`, `method_taxonomy`, `shared_examples`, `evaluation_outlook`, `appendices`.

## outline.json schema
```json
{
  "topic": "...",
  "book_sections": [{"id": "preface", "title": "Preface"}, ...],
  "parts": [{"id": "interpretable", "title": "Interpretable Methods", "family_ids": ["fam_a"]}],
  "families": [{
    "id": "sliding_window_attention", "title": "Sliding-Window Attention",
    "community_id": "cm_01",
    "method_ids": ["nsa", "xattention"],
    "neighbor_family_ids": ["kv_cache_eviction"],
    "knowledge_gaps_to_explain": [], "known_concepts_assumed": []
  }],
  "methods": [{
    "id": "nsa", "title": "NSA: Natively Sparse Attention",
    "arxiv_id": "2502.11089",
    "family_id": "sliding_window_attention",
    "neighbor_method_ids": ["xattention", "pyramidkv"],
    "knowledge_gaps_to_explain": [], "known_concepts_assumed": []
  }]
}
```

`taxonomy.json`: list of communities with `central_concept`, `node_ids`, `promoted_paper_ids`, `background_paper_ids`, `size`.

## Hard rules
- Every Stage 12 payload `verified_full_text_arxiv_ids` entry produces exactly one method.
- No method has an `arxiv_id` outside Stage 12 payload `verified_full_text_arxiv_ids`.
- Every method's `family_id` resolves to a family.
- Every method ID appears in exactly one family `method_ids` list.
- Every family has ≥ 1 method.
- No duplicate normalized family titles.
- No family title is a sentence or benchmark-result claim.
- No method ID is a raw arXiv ID or looks like a paper section heading.
- `knowledge_gaps_to_explain` (any level) ⊆ gap-report concepts.
- `book_sections` is the fixed 8-element list.
- `parts` is present with 2..5 entries; every family belongs to exactly one part.

Before writing `outline.json`, self-validate these rules and fix violations in memory. Do not write a draft outline that relies on downstream cleanup.

## Success
- 8 book_sections; ≥ 1 family; one method per Stage 12 payload `verified_full_text_arxiv_ids` entry; no extra methods; family_ids resolve.
