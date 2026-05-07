---
name: weak-evidence-extraction
description: Cheap first-pass extraction of paper structure from abstract, alphaXiv overview, and Semantic Scholar metadata.
---

# Weak Evidence Extraction

## Goal
Produce one weak-evidence card per paper without reading full Markdown.

## Inputs
- `02_paper_pool/paper_pool.json` (arxiv_id → abstract)
- alphaXiv overview Markdown (via MCP `get_alphaxiv_overview`)
- Semantic Scholar metadata (via MCP `get_paper_metadata`)

## Outputs
- `03_overviews/alphaxiv_overviews/{arxiv_id}.json` — raw overview
- `03_overviews/semantic_scholar/{arxiv_id}.json` — raw metadata
- `04_weak_evidence/{arxiv_id}.json` — extracted card

## Rules
- Call MCP tools at most once per paper. If a call fails, log and continue with what is available.
- Mark `trust_level` as `OVERVIEW_DERIVED` when overview was used, `REPORT_DERIVED` when only metadata + abstract were available.
- The `reader_needed_concepts` field is the most important. List concepts a reader must understand to follow the paper. Aim for 5–15 concepts.
- Do not invent claims. If a field is unknown, use an empty list.
- Output valid JSON.

## Output schema (per paper)
```json
{
  "arxiv_id": "2304.08485",
  "title": "",
  "year": 0,
  "trust_level": "OVERVIEW_DERIVED",
  "paper_type": "method | benchmark | dataset | survey | application | theory | unknown",
  "topic_tags": [],
  "problem": [],
  "solution": [],
  "methods": [],
  "datasets": [],
  "benchmarks": [],
  "metrics": [],
  "baselines": [],
  "results": [],
  "limitations": [],
  "mentioned_entities": [],
  "mentioned_papers": [],
  "reader_needed_concepts": [],
  "book_usage": {
    "possible_chapters": [],
    "role": "core | support | benchmark | dataset | background | limitation | exclude",
    "importance_score_1_to_5": 0
  }
}
```

## Success check
- One file in `04_weak_evidence/` per paper in `paper_pool.json`.
- Every file has non-empty `reader_needed_concepts` (or an explicit empty list with `paper_type: unknown` if extraction completely failed).
