---
name: verification
description: Verify chapter claims against source nodes and check knowledge-gap coverage.
---

# Verification

## Goal
Catch unsupported claims, overstated results, missing background, and over-explained known concepts.

## Inputs
- `14_chapters/{chapter_id}.md`
- `13_chapter_packs/{chapter_id}_pack.json`
- `09_pageindex/trees/*.tree.json` and `.nodes.json`
- `08_full_markdown/{arxiv_id}.md` (via MCP `get_paper_section`)
- `06_expansion/known_concepts_snapshot.json`
- `06_expansion/knowledge_gap_report.json`

## Outputs
- `15_verification/{chapter_id}_verification.json`
- `15_verification/verification_summary.csv`

## Rules
- For each non-trivial claim with a citation `[arxiv:ID, node_id]`, fetch that section and judge: `supported`, `partially_supported`, `unsupported`, `overstated`.
- For each high-priority knowledge gap from `knowledge_gap_report.json`, judge `covered` / `missing` / `overexplained` based on the chapter text.
- For KB-known concepts that the chapter explains in detail (more than a sentence), flag as `overexplained_background`.
- A claim that invents a dataset, metric, or numerical result is `unsupported`.

## Output schema
```json
{
  "chapter_id": "chapter_01",
  "claims": [
    {"text": "...", "citation": "arxiv:2304.08485, s.03.02", "verdict": "supported", "reason": ""}
  ],
  "knowledge_gap_coverage": [
    {"concept": "CLIP vision encoder", "status": "covered", "reason": ""}
  ],
  "overexplained_known_concepts": [
    {"concept": "Transformer", "reason": "Two paragraphs of explanation; KB lists it as known."}
  ],
  "summary": {
    "claims_total": 0,
    "claims_unsupported": 0,
    "claims_overstated": 0,
    "gaps_covered": 0,
    "gaps_missing": 0,
    "overexplained_count": 0
  }
}
```

## Success check
- File exists.
- `summary.claims_unsupported == 0` and `summary.gaps_missing == 0` for the run to pass MVP success criteria.
