---
name: paper-pool-expansion
description: Expand the paper pool only to cover important unknown concepts.
---

# Paper Pool Expansion

## Goal
For each item in the expansion queue, find a small number of foundational papers that explain the unknown concept, and add only the accepted ones to the pool.

## Inputs
- `06_expansion/expansion_need_queue.json`
- `02_paper_pool/paper_pool.json` (to dedupe)

## Outputs
- `06_expansion/expansion_round_01.json` — full search log for the round
- `06_expansion/accepted_candidates.csv`
- `06_expansion/rejected_candidates.csv`
- updated `02_paper_pool/paper_pool.json` and `02_paper_pool/paper_pool.csv`

## Rules
- Run exactly ONE expansion round in MVP.
- For each queue item, run `bulk_normal_start_search` with the item's `search_queries`.
- Accept a candidate only if ALL hold:
  - directly explains the unknown concept (foundational paper, survey, or canonical reference)
  - has an arXiv ID
  - is not already in the pool
  - is needed to understand a key paper in the run
- Reject if loosely related, application-specific, duplicate, or low relevance.
- Cap: at most `max_papers_to_add` papers per gap (default 3). Stop early when reached.
- Total cap across the round: ≤ 15 new papers (5 gaps × 3 papers).
- Every accepted paper record must include `added_for_gap` and `why_needed`.

## Accepted CSV columns
```
arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed
```

## Pool record extension for expansion papers
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

## Success check
- `accepted_candidates.csv` and `rejected_candidates.csv` exist.
- Updated `paper_pool.json` has no duplicate arxiv_ids.
- Every new paper has `added_for_gap` and `why_needed`.
- Total new papers ≤ 15.
