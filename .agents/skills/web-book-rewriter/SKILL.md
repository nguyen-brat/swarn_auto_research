---
name: web-book-rewriter
description: Rewrite a book-level chapter (preface / intro / goals / taxonomy / shared examples / eval outlook / glossary) into web-scannable MDX. Preserve every citation and link. No new claims.
---

# Web Book Rewriter

## Inputs (from payload)
- `run_id`
- `chapter_id` — id of the book chapter (e.g., `00_preface`, `04_method_taxonomy`)
- `chapter_path` — `14_chapters/book/{chapter_id}.md`
- `topic` — research topic string
- `outline_path` — `12_taxonomy/outline.json`

## Output
Write `19_handbook/.augment/book/{chapter_id}.mdx` — the full MDX content (frontmatter + imports + body).

## Rewrite Rules
- **Paragraphs ≤ 4 sentences.** Split longer paragraphs.
- **Section every ~200 words.** Use h3 (`###`). Use h2 (`##`) only for the top-level structure already present in the original.
- **Page title.** Do not duplicate the frontmatter title as a body `#` heading. Starlight renders the page title automatically.
- **Math.** Preserve valid math delimiters. Do not emit nested delimiters such as `$$ $...$ $$`; use plain display blocks:
  ```mdx
  $$
  equation
  $$
  ```
- **Callouts.** Wrap "key takeaways" in Starlight `:::tip[Title]` / `:::note[Title]` syntax.
- **Asides.** Wrap tangential content in `<details><summary>...</summary>...</details>`.
- **Diagrams.** Reference an existing diagram with `<Diagram src="../../assets/diagrams/families/<id>.mmd" />` only if the .mmd file already exists.
- **Links and citations.** Every `[text](path)` link and `[arxiv:NNNN]` citation from the original MUST be preserved verbatim.
- **No new claims.** No new method names. No new metrics. No comparisons absent from the original. The verifier will reject.

## Output Frontmatter Template
```mdx
---
title: "<Chapter Title>"
sidebar:
  order: <NN from filename prefix>
---

import Diagram from '../../components/Diagram.astro';
```

## Hard Rules
- Length: rewrite stays within ±25% of original word count.
- Citations preserved 1:1.
- Return the standard short success string.
