---
name: family-chapter-writing
description: One taxonomy/sub-topic chapter connecting a family of methods — mechanism overview, use cases, comparison, and boundaries.
---

# Family Chapter Writing

## Inputs
- `family_ids` (sharded slice)
- `13_chapter_packs/families/{family_id}_pack.json`
- `Book_style.md`

## Output
- `14_chapters/families/{family_id}.md`

## Required sections (exact `##` headings, in order)
1. `## Summary` — define the family in 2–4 sentences.
2. `## Motivation` — why this family exists; cite pack's problem framing.
3. `## Core Idea` — shared intuition.
4. `## Common Pipeline` — shared workflow / architecture: inputs, representation, training/inference choice, system bottleneck.
5. `## Main Variants` — compare important variants. **MUST include a Markdown table** with header `Method | Core mechanism | When it helps | When it hurts | Cite`, one row per `pack.method_ids`. Values verbatim from `pack.comparison_rows`. Cite is `[arxiv:ID, node_id]`.
6. `## Representative Methods` — bulleted list, each entry: `- [Method Title](../methods/{method_id}.md) — one-line tagline.`
7. `## Strengths` — 3–6 bullets, each ending with citation.
8. `## Limitations` — 3–6 bullets, each ending with citation.
9. `## When to Use` — practical decision guidance.
10. `## Related Families` — one paragraph per `neighbor_family_id` with citations on boundary claims; include cross-family overlap notes.

A trailing `## References` is allowed but not required.

## Writing contract
- This is the chapter for a taxonomy sub-topic of the user's main topic. It must teach the sub-topic, not merely list methods.
- Explain the shared design pattern across the family: inputs, representation, training/inference choice, system bottleneck, and why the family exists.
- The comparison must be analytical. A row like "streaming inference, audio tokenization" is not enough; explain mechanism, when it helps, and failure mode from `pack.comparison_rows`.
- If a family contains methods that are too broad or unrelated, explicitly mark boundary cases and explain the overlap rather than pretending the group is homogeneous.
- Do not write generic filler such as "serves as a navigation layer" or "variations on the same engineering pressure" without evidence.

## Hard rules
- Defer method-level details to method chapters.
- `## Main Variants` contains a comparison table; every row cites a node.
- Every `## Related Families` boundary claim cites a node.
- Method links use relative path `../methods/{method_id}.md`.

## Length
- 1000–1800 words. Start with `# {family_title}`.

## Success
- File starts with `# `; all 10 `##` sections present in exact order.
- `## Main Variants` contains a comparison table with ≥ 1 row per method.
- `## Strengths` and `## Limitations` each have ≥ 3 bullets.
- Word count 1000–1800.
