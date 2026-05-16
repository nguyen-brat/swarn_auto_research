---
name: paper-pool-expansion
description: Add foundational papers that EXPLAIN unknown concepts. Relevance is the only filter — no count cap.
---

# Paper Pool Expansion

## Inputs
- `gap_items` — sharded slice of `06_expansion/expansion_need_queue.json` items
- `02_paper_pool/paper_pool.json` (read-only; for dedupe)

## Outputs (per shard)
- `06_expansion/expansion_round_01_shard_{shard_id}.json` (status='completed' when slice had items, even if zero accepted)
- `06_expansion/accepted_candidates_shard_{shard_id}.csv`
- `06_expansion/rejected_candidates_shard_{shard_id}.csv`

## Outputs (orchestrator merge)
- `06_expansion/expansion_round_01.json`, `accepted_candidates.csv`, `rejected_candidates.csv`
- Updated `02_paper_pool/paper_pool.json` and `.csv`

## Rules
- Exactly ONE round in MVP.
- Non-empty slice → MUST search every item. Skipping is never valid.
- "Seed papers mention X" ≠ "seed papers explain X" — only the second substitutes for expansion.
- Per item: call MCP `gap_paper_search` with the item's `search_queries`, positive keywords derived from the gap concept/query terms, and only narrow negative keywords for obvious off-topic domains. The tool combines Hugging Face paper search and alphaXiv paper search. Log the returned `queries`, `total_input`, `total_kept`, `query_audit`, and `output_path` into the round file even when every result is rejected.
- Do not call `bulk_normal_start_search` in Stage 6. That tool is reserved for Stage 1 seed-pool discovery.
- Accept only when ALL hold: directly explains the concept (foundational/survey/canonical) AND has arxiv_id AND not already in pool AND needed for a key paper.
- No paper-count cap. Reject loosely-related / application-specific / duplicate / low-relevance with `why_rejected`.
- Every acceptance has `added_for_gap` and `why_needed`.

## Accepted CSV columns
```
arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed
```

## Pool record extension
```json
{
  "arxiv_id": "2103.00020",
  "status": "DISCOVERED",
  "source": "knowledge_gap_expansion",
  "added_for_gap": "CLIP vision encoder",
  "needed_by_papers": ["2304.08485"],
  "candidate_role": "foundational",
  "abstract": "...",
  "expansion_round": 1
}
```

## Success
- Both CSVs exist; `paper_pool.json` has no duplicates; every new paper has `added_for_gap` + `why_needed`.
