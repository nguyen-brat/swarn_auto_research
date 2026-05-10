---
name: method-chapter-writing
description: One method chapter using Book_style's 10-section template. Reproduce equations and pseudocode VERBATIM from the pack — never paraphrase math.
---

# Method Chapter Writing

## Inputs
- `method_ids` (sharded slice)
- `13_chapter_packs/methods/{method_id}_pack.json` — self-contained
- `Book_style.md`
- `06_expansion/known_concepts_snapshot.json` (never re-explain these)

## Output
- `14_chapters/methods/{method_id}.md`

## Required sections (in order, exact `##` headings)
1. `## Summary` — 2–5 sentences.
2. `## Motivation` — why this method, citing the pack's problem framing.
3. `## Intuition` — mental model. No equations.
4. `## Theory` — every `pack.structured.equations[]` reproduced VERBATIM as `$$ ... $$`. Below each: 1-line plain caption + `[arxiv:ID, node_id]` cite.
5. `## Algorithm` — `pack.structured.algorithms[].pseudocode` reproduced VERBATIM in a fenced ```text block. Then numbered `steps`. Cite source.
6. `## Worked Example` — concrete numbers from `pack.structured.hyperparameters` and the pack's `example` section.
7. `## Interpretation` — how to read outputs/plots/scores.
8. `## Strengths` — bulleted, 3–6, each ends with citation.
9. `## Limitations` — bulleted, 3–6, each ends with citation.
10. `## Practical Guidance` — lead with **when to use / when not to use** (1–2 cited paragraphs). Then a sub-bullet list of artifacts (libraries, models, codebases). Every artifact MUST appear in the pack. If none, write the literal phrase "no concrete artifacts" (or "none were available") + lookup pointers.
11. `## Related Methods` — one paragraph per `pack.neighbors` entry, ≥ 2 when pack has ≥ 2.

## Writing contract
- This is a method-design chapter, not a paper abstract and not a source excerpt dump.
- Use `section_text` as evidence, then synthesize: explain the model components, data flow, training/inference procedure, objective, design tradeoffs, and evaluation interpretation in your own technical prose.
- Do NOT paste raw section headings, bullet lists of paper sections, table captions, "Baselines." labels, or copied evaluation lists as chapter content. If a source section lists baselines, explain what each baseline is testing and why it matters for this method's design.
- Do NOT create empty sections containing only a citation such as `[arxiv:ID, s.01]`.
- Do NOT write placeholders like `None.`, `Too thin.`, `No explicit hyperparameters were extracted...` as the whole substance of a required section.
- If theory, algorithm, example, or limitations has no non-empty `section_text` in the pack, stop and return a failure for that method. Do not write a chapter from an empty pack.
- Every required section except Practical Guidance and Related Methods should contain at least one explanatory paragraph of 3+ sentences before citations.

## Hard rules
- Equations VERBATIM as display math. Do not paraphrase LaTeX. The 1-line caption goes BELOW the equation, not in place.
- Pseudocode VERBATIM in fenced blocks.
- Theory has ≥ 1 `$$` when pack has equations. Algorithm has ≥ 1 fenced block OR a numbered list of length ≥ 3 when pack has algorithms.
- Artifact grounding: every named library/codebase/model/comparison must appear in `pack.structured` or in a `pack.section_plan[*].source_nodes[*].section_text`.
- Cite every non-trivial claim inline as `[arxiv:ID, node_id]`.
- KB-known concepts: brief mention only, no re-explanation.

## Length
- 1500–3000 words. Start with `# {method_title}`.

## Success
- File starts with `# `; all 11 `##` sections present in order.
- No citation-only required sections, no placeholder sections, and no copied source-heading lists.
- Theory has equations when pack provides them.
- Algorithm has pseudocode block or ≥ 3-step numbered list when pack provides algorithms.
- Strengths and Limitations: ≥ 3 bullets each.
- Related Methods: ≥ 2 paragraphs when pack has ≥ 2 neighbors.
- Word count 1500–3000. Every named artifact appears in pack.
