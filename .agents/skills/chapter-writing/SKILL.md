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

## Depth and form requirements

These prevent the common "10 sections × 1 abstract paragraph" failure mode.

- **Length floor.** Aim for 1200–2500 words. Shorter chapters skip detail; longer chapters are not rewarded.
- **"How it works" is the load-bearing section.** When the chapter discusses ≥ 2 methods, this section must dedicate at least one paragraph per method, naming the specific mechanism (algorithmic step, equation reference, or architecture component) — not just naming the paper.
- **Comparison table required when ≥ 3 methods are discussed.** Use a Markdown table with columns suited to the topic. For methods, prefer: `Method | Core mechanism | When it helps | When it hurts | Cite`. The cite column is the inline arxiv reference.
- **Worked example must be concrete.** Specify at least one of:
  - input/output sizes (e.g. "8K-token trace"), runtime/cost numbers, or accuracy/perplexity numbers — only when the source paper actually reports them; otherwise
  - a step-by-step walkthrough that names the input, the model's intermediate state, and the output.
  Do not write "suppose you have a long input" without saying what the model actually does at each step.
- **Strengths and Limitations are bullet lists**, not paragraphs. Each bullet starts with the condition or property and ends with the citation. Aim for 3–6 bullets per list.
- **Implementation notes must name at least two concrete artifacts**: a library, model release, framework, or repository link mentioned in the cited papers (e.g. `vllm`, `transformers`, `flash-attn`, the official paper repo). If the chapter pack's papers do not provide concrete artifacts, say so explicitly and list what a reader should look up instead.
- **No fluff sentences.** Sentences like "this is an important area" or "researchers have explored many approaches" add no information. Cut them.

## Success check
- `14_chapters/chapter_NN.md` exists and meets the length floor.
- Every section maps to at least one source node listed in the chapter pack.
- The chapter includes Strengths and Limitations sections, formatted as bullet lists.
- "How it works" has one paragraph per method when multiple are discussed.
- Comparison table present when ≥ 3 methods are compared.
- Worked example contains at least one concrete number or a step-by-step walkthrough.
- Implementation notes name ≥ 2 concrete artifacts (or explicitly note their absence).
