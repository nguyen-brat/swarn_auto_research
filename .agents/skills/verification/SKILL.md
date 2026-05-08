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

## Form checks (from chapter-writing/SKILL.md)

These catch a chapter that is technically grounded but structurally thin.

- **word_count** below 1200.
- **comparison_table_missing** if the chapter discusses ≥ 3 methods and contains no Markdown table.
- **how_it_works_thin** if the chapter discusses ≥ 2 methods and "How it works" (or equivalent) has fewer paragraphs than methods.
- **strengths_not_list** if Strengths is one paragraph instead of bullets (≥ 3 bullets).
- **limitations_not_list** if Limitations is one paragraph instead of bullets (≥ 3 bullets).
- **worked_example_abstract** if the worked example contains no concrete number AND no step-by-step walkthrough naming input → intermediate state → output.
- **implementation_notes_empty** if Implementation notes does not name ≥ 2 concrete artifacts (libraries, model releases, frameworks, repos), unless the chapter explicitly states none were available.

Each form failure is recorded with the offending excerpt and listed in `summary.form_issues`.

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
  "form_issues": [
    {"check": "comparison_table_missing", "detail": "Discusses 5 methods (Mamba, Samba, Transformer-XL, Longformer, PagedAttention) with no comparison table."}
  ],
  "summary": {
    "claims_total": 0,
    "claims_unsupported": 0,
    "claims_overstated": 0,
    "gaps_covered": 0,
    "gaps_missing": 0,
    "overexplained_count": 0,
    "word_count": 0,
    "form_issue_count": 0
  }
}
```

## Success check
- File exists.
- For MVP success: `claims_unsupported == 0`, `gaps_missing == 0`, `form_issue_count == 0`, and `word_count >= 1200`.
- A run with `form_issue_count > 0` is functionally complete but should NOT be reported as MVP-passing; the orchestrator should log it and the user can choose to re-dispatch `chapter_writer` with the verifier output as feedback.
