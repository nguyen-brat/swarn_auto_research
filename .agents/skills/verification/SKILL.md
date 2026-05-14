---
name: verification
description: Verify chapters against verified-evidence with per-type form profiles. Verbatim cited equation/pseudocode blocks pass automatically.
---

# Verification

## Inputs
- `chapter_targets` — typed IDs (`book:{id}` / `family:{id}` / `method:{id}`)
- `14_chapters/{book|families|methods}/...`
- `13_chapter_packs/{book|families|methods}/...`
- `10_verified_evidence/{arxiv_id}.json`
- `09_pageindex/trees/*.tree.json`
- `08_full_markdown/{arxiv_id}.md` (via `get_paper_section`)
- `06_expansion/known_concepts_snapshot.json`, `knowledge_gap_report.json`
- `12_taxonomy/outline.json`

## Outputs
- `15_verification/{book|families|methods}/{id}_verification.json` — the ONLY artifact this agent writes. Overwrite in place on rewrite/reverify.

NEVER write `verification_summary.csv` or any `verification_summary_shard_*.csv`. The parent orchestrator rebuilds the canonical summary deterministically from per-target JSONs after all dispatches return.

## Claim verdicts
For every `[arxiv:ID, node_id]` citation: `supported`, `partially_supported`, `unsupported`, or `overstated`.

### Verbatim cited block rule (auto-supported)
A `$$ ... $$` block or fenced code block (```text or unlanguaged) whose contents appear as a substring of the cited node's source text (read via `get_paper_section`) → `supported` automatically.

### Verified-evidence match
Else `supported` only if `10_verified_evidence/{ID}.json` has a `claim/equation/algorithm/hyperparameter/complexity/neighbor` with the same `source_node_id` AND fetched section text agrees.

### Artifact grounding (fabrication check)
Every named library/codebase/model/comparison must appear in the chapter's pack (either in `pack.structured` or in any `pack.section_plan[*].source_nodes[*].section_text`). Else mark surrounding claim `unsupported`. Do NOT accept names from `04_weak_evidence/`.

## Knowledge-gap coverage
Book + method only (skip family). Each high-priority gap: `covered` / `missing` / `overexplained` (KB-known concepts with > 1 sentence of explanation).

## Section detection
Do this FIRST, case-insensitive on heading text. Synonyms allowed:

| Logical section  | Synonyms |
|---|---|
| Theory          | "theory", "theoretical foundation", "formalism" |
| Algorithm       | "algorithm", "procedure", "method steps" |
| Worked Example  | "worked example", "example", "case study" |
| Practical Guidance | "practical guidance", "software", "implementation notes", "tools and libraries" |
| Related Methods | "related methods", "related work and methods", "neighbors" |
| Strengths       | "strengths", "advantages", "when it works well" |
| Limitations     | "limitations", "weaknesses", "failure modes", "caveats" |

If no synonym matches → `<section>_section_missing`. Never report depth issues for an absent section.

## Form profile per chapter type

High word count is non-blocking for handbook output. Report `*_word_count_high`
as a warning if useful, but do not put it in `form_issues` and do not include it
in `summary.form_issue_count`. Low word count remains a blocking form issue.

### `method:*`
- Required headings, exactly and in order: `## Summary`, `## Motivation`, `## Intuition`, `## Theory`, `## Algorithm`, `## Worked Example`, `## Interpretation`, `## Strengths`, `## Limitations`, `## Practical Guidance`, `## Related Methods`.
- `theory_missing_equations` — Theory has 0 `$$` AND pack has ≥ 1 equation.
- `algorithm_missing_pseudocode` — Algorithm has 0 fenced block AND no numbered list of length ≥ 3, AND pack has ≥ 1 algorithm.
- `example_abstract` — Worked Example has no concrete number AND pack provides hyperparameters or numeric results.
- `citation_only_section` — any required section except Practical Guidance/Related Methods has only citations or fewer than 20 non-citation words.
- `placeholder_section` — section body is `None.`, "Too thin.", "No explicit hyperparameters were extracted..." alone, or equivalent placeholder text.
- `copied_source_outline` — section mostly consists of source paper headings, table captions, "Baselines." labels, or repeated bullet lists rather than explanatory prose.
- `strengths_thin` / `limitations_thin` — < 3 bullets.
- `related_methods_thin` — < 2 paragraphs AND pack has ≥ 2 neighbors.
- `method_word_count_low` — < 1500. `method_word_count_high` — > 3000 is a warning only.

### `family:*`
- Required headings, exactly and in order: `## Summary`, `## Motivation`, `## Core Idea`, `## Common Pipeline`, `## Main Variants`, `## Representative Methods`, `## Strengths`, `## Limitations`, `## When to Use`, `## Related Families`.
- `comparison_table_missing` — no Markdown table.
- `comparison_row_count_mismatch` — table rows ≠ `len(pack.method_ids)`.
- `core_idea_missing` — missing `## Core Idea`.
- `family_placeholder_prose` — generic navigation prose without concrete mechanism/use/failure claims from pack rows.
- `method_links_broken` — link target file doesn't exist under `14_chapters/methods/`.
- `family_word_count_low` — < 1000. `_high` — > 1800 is a warning only.

### `book:*`
Per `section_id`, check the subsection list and word range from `book-section-writing/SKILL.md`. Specific extras:
- `motivating_intro` — ≥ 1 citation in the anecdote.
- `core_concepts` — one subsection per gap concept.
- `goals` — bulleted list with ≥ 2.
- `method_taxonomy` — ≥ 1 family link per family and ≥ 1 method link per method in outline.
- `shared_examples` — ≥ 1 worked example with citation.
- `evaluation_outlook` — ≥ 3 distinct benchmark/metric names from verified-evidence.
- `appendices` — References lists every promoted paper.
- `book_placeholder_prose` — generic boilerplate or "regenerated deterministically" placeholder remains in final chapter.
- Other ranges → `<section>_word_count_low`; `<section>_word_count_high` is a warning only. Missing required subsections → `<subsection>_missing`.

## Output schema
```json
{
  "chapter_target": "method:nsa",
  "chapter_type": "method",
  "claims": [{"text":"", "citation":"arxiv:..., s.05.02",
              "verdict":"supported", "reason":"verbatim equation match"}],
  "knowledge_gap_coverage": [{"concept":"", "status":"covered|missing|overexplained", "reason":""}],
  "form_issues": [{"check":"theory_missing_equations", "detail":"", "excerpt":""}],
  "warnings": [{"check":"method_word_count_high", "detail":"", "excerpt":""}],
  "summary": {
    "claims_total": 0, "claims_unsupported": 0, "claims_overstated": 0,
    "gaps_covered": 0, "gaps_missing": 0,
    "word_count": 0, "form_issue_count": 0,
    "equations_rendered": 0, "pseudocode_blocks": 0
  }
}
```

## Success
- File at canonical verification path.
- `passed` iff `claims_unsupported == 0 AND gaps_missing == 0 AND form_issue_count == 0`.
  High-word-count warnings do not affect `passed`.
