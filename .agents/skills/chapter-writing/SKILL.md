---
name: chapter-writing
description: Write one handbook chapter from a chapter pack, citing arXiv IDs and source nodes.
---

# Chapter Writing

## Goal
Produce one chapter that explains a topic clearly, assuming KB-known concepts and explaining only necessary unknown concepts.

## Inputs
- `13_chapter_packs/chapter_NN_pack.json`
- `09_pageindex/trees/{arxiv_id}.tree.json` and `.nodes.json` for cited papers
- `08_full_markdown/{arxiv_id}.md` (read sections via MCP `get_paper_section` to keep context small)
- `06_expansion/known_concepts_snapshot.json`
- `Book_style.md` (style rules)

## Outputs
- `14_chapters/chapter_NN.md`

## Rules
- Treat KB-known concepts as already understood. Brief mention only; never an explanation.
- Explain unknown but necessary concepts in proportion to their centrality:
  - central → dedicated subsection
  - supporting → short paragraph
  - minor → footnote/glossary or skip
- Every non-trivial claim cites an arXiv ID inline like `[arxiv:2304.08485, s.03.02]`.
- Follow `Book_style.md` chapter pattern: definition → motivation → intuition → formal explanation → worked example → interpretation → strengths → limitations → practical guidance → tools.
- Never invent datasets, metrics, or numerical results.
- Do not over-explain known concepts. The verifier flags this.

## Success check
- `14_chapters/chapter_NN.md` exists.
- Every section maps to at least one source node listed in the chapter pack.
- The chapter includes Strengths and Limitations sections.
