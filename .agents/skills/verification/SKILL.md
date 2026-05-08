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

### Section detection (do this FIRST, before any form check)

Headings vary in casing and synonyms across chapters. Before reporting any
section as "missing", scan all `##` and `###` headings in the chapter and
match them case-insensitively against this synonym table. Use the FIRST
match. Only report a section missing if NO synonym matches.

| Logical section       | Accepted heading synonyms (case-insensitive, trim whitespace) |
|-----------------------|---------------------------------------------------------------|
| `how_it_works`        | "how it works", "mechanism", "how the methods work", "method details", "technical details", "algorithm" |
| `worked_example`      | "worked example", "example", "concrete example", "case study", "walkthrough" |
| `strengths`           | "strengths", "when it works well", "advantages" |
| `limitations`         | "limitations", "weaknesses", "failure modes", "caveats", "tradeoffs" |
| `comparison`          | "comparison table", "comparison", "method comparison", "side by side" |
| `implementation_notes`| "implementation notes", "tools", "libraries", "implementation", "tools and implementation", "implementation and tools" |
| `practical_guidance`  | "practical guidance", "when to use", "when to use and when not to use", "guidance" |

If a check's section is not found via this table, the issue is
**`<section>_section_missing`**, NOT the depth-related issue. Do not record
`how_it_works_thin` when the section is genuinely absent — record
`how_it_works_section_missing` instead. The two are different problems and
the chapter writer needs different feedback for each.

### Depth checks (only after the section is located)

For each check, parse the chapter's section bounded by the matched heading
and the next `##` heading (or end of file). Then evaluate:

- **word_count** below 1200, computed across the whole chapter.
- **comparison_table_missing** if the chapter discusses ≥ 3 methods and contains no Markdown table anywhere (table = at least one line starting with `|` followed by a `| --- |` separator).
- **how_it_works_thin** if `how_it_works` is found AND the chapter discusses ≥ 2 methods AND the section's paragraph count is fewer than the number of methods. A "paragraph" is a run of non-blank lines separated by blank lines; bold-prefixed paragraphs like `**Mamba.** ...` count as one paragraph each.
- **strengths_not_list** if `strengths` is found AND the section contains zero Markdown bullet lines (`- ` or `* `) OR fewer than 3 bullets.
- **limitations_not_list** same check on `limitations`.
- **worked_example_abstract** if `worked_example` is found AND the section contains NEITHER a digit run of length ≥ 1 (e.g. "8K", "32x", "0.9") NOR all three of the substrings `input`, `state`, `output` (case-insensitive).
- **implementation_notes_empty** if `implementation_notes` is found AND fewer than 2 backtick-quoted artifacts (`` `vllm` ``, `` `transformers` ``, etc.) OR proper-noun artifacts (capitalized library/model/repo names) are mentioned, UNLESS the section contains the literal phrase "no concrete artifacts" or "none were available".

Each form failure is recorded as a `form_issues` entry with `check`,
`detail`, and an `excerpt` field showing up to 240 chars of the matched
text (or "section not found" when the section is genuinely missing). Both
section-missing and depth issues count toward `summary.form_issue_count`.

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
    {
      "check": "comparison_table_missing",
      "detail": "Discusses 5 methods (Mamba, Samba, Transformer-XL, Longformer, PagedAttention) with no comparison table.",
      "excerpt": ""
    },
    {
      "check": "how_it_works_section_missing",
      "detail": "No heading matched any synonym for 'How it works'.",
      "excerpt": "section not found"
    }
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
