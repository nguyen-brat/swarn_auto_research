---
name: paper-ranking
description: Score every paper and promote every paper meeting the relevance threshold, with no upper cap.
---

# Paper Ranking

## Inputs
- `run_id`
- `min_promote_score` (default `0.45`)
- `02_paper_pool/paper_pool.json`
- `04_weak_evidence/*.json`
- `05_weak_graph/weak_global_graph.json`
- `06_expansion/knowledge_gap_report.json`

## Outputs
Write all outputs under `07_scoring/`:

- `paper_scores.csv`
- `promotion_candidates.csv`
- `promoted_papers.json`

`paper_scores.csv` columns:

```csv
arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,implementation_impact,chapter_need,knowledge_gap_boost,final_score
```

`promotion_candidates.csv` contains every paper sorted descending by `final_score`.

`promoted_papers.json` contains rows above threshold sorted descending, with schema:

```json
{"arxiv_id": "...", "final_score": 0.0, "reason": "...", "is_gap_paper": false}
```

## Scoring Formula
Clamp each component to `[0,1]`.

```text
final_score = 0.35*topic_relevance + 0.20*graph_centrality
            + 0.15*citation_or_influence + 0.10*recency
            + 0.10*implementation_impact + 0.10*chapter_need
```

Components:

- `topic_relevance = weak_evidence.importance_score_1_to_5 / 5`
- `graph_centrality = node_degree / max_degree` in `weak_global_graph`
- `citation_or_influence = log1p(citationCount) / log1p(10000)`; default `0`
- `recency = clamp((year - 2018) / 8, 0, 1)`; default `0.5`
- `implementation_impact = 1` if the paper introduces a method or codebase used by another pool paper, else `0`
- `chapter_need = 1` if core/support entry for dominant graph community, else `0.5` if support, else `0`

## Knowledge Gap Boost
Add `knowledge_gap_boost` up to `+0.20` only when all conditions hold:

- `paper.source == 'knowledge_gap_expansion'`
- its gap priority is `>= 0.70`
- `paper.candidate_role in {'foundational','survey'}`

## Hard Rules
- Score every paper; promote every paper with `final_score >= min_promote_score`.
- Do not impose any upper cap on promotions.
- You must write all three output files.
- Never write only `promoted_papers.json`.
- Every `paper_pool` `arxiv_id` must appear exactly once in `paper_scores.csv` and `promotion_candidates.csv`.
- `promotion_candidates.csv` must be sorted by `final_score` descending.
- If zero papers meet the threshold, emit only the highest-scored paper so downstream stages do not stall.

## Validation-Sensitive Outputs
- `paper_scores.csv` must include every `paper_pool` `arxiv_id` exactly once.
- `promotion_candidates.csv` must include the same rows sorted by `final_score` descending.
- `promoted_papers.json` must include every row with `final_score >= min_promote_score`.
- Do not cap the promoted list.
- If zero rows meet the threshold, promote exactly the top-scored paper as fallback.

## Success / Return Contract
Return:

```text
ok: P scored, N promoted (threshold={min_promote_score})
```
