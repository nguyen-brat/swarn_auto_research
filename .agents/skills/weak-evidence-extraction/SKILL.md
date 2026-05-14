---
name: weak-evidence-extraction
description: First-pass paper card from abstract + alphaXiv overview + Semantic Scholar metadata.
---

# Weak Evidence Extraction

## Inputs
- `arxiv_ids` (sharded slice; unsharded fallback: all of `02_paper_pool/paper_pool.json`)
- MCP `get_alphaxiv_overview` (one id per call)
- MCP `get_paper_metadata` (call ONCE per shard with the full slice — batching + 429 backoff internal)

## Outputs
- `03_overviews/alphaxiv_overviews/{arxiv_id}.json` — raw overview
- `03_overviews/semantic_scholar/{arxiv_id}.json` — raw metadata
- `04_weak_evidence/{arxiv_id}.json` — extracted card

## Rules
- `trust_level` = `OVERVIEW_DERIVED` when overview was used, else `REPORT_DERIVED`.
- `reader_needed_concepts` is the load-bearing field — 5–15 concepts a reader must know to follow the paper.
- Never invent claims. Unknown fields → empty list.
- Tool failure on a single paper: log and continue with what's available.

## Schema
```json
{
  "arxiv_id": "", "title": "", "year": 0,
  "trust_level": "OVERVIEW_DERIVED",
  "paper_type": "method|benchmark|dataset|survey|application|theory|unknown",
  "topic_tags": [], "problem": [], "solution": [],
  "methods": [], "datasets": [], "benchmarks": [], "metrics": [],
  "baselines": [], "results": [], "limitations": [],
  "mentioned_entities": [], "mentioned_papers": [],
  "reader_needed_concepts": [],
  "book_usage": {
    "possible_chapters": [],
    "role": "core|support|benchmark|dataset|background|limitation|exclude",
    "importance_score_1_to_5": 0
  }
}
```

## Success
- One file per id in slice. `reader_needed_concepts` non-empty (or explicit empty + `paper_type: unknown` if extraction fully failed).
