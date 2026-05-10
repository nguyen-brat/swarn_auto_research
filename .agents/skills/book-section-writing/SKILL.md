---
name: book-section-writing
description: Eight book-level chapters wrap the family/method chapters into a real handbook. Each section has its own form rules.
---

# Book Section Writing

## Inputs
- `section_ids` (sharded slice; values from the table below)
- `13_chapter_packs/book/{section_id}_pack.json`
- `Book_style.md`

## Output filenames (under `14_chapters/book/`)
| section_id           | filename                       | word range |
|----------------------|--------------------------------|------------|
| `preface`            | `00_preface.md`                | 400–800    |
| `motivating_intro`   | `01_motivating_intro.md`       | 600–1200   |
| `core_concepts`      | `02_core_concepts.md`          | 800–1500   |
| `goals`              | `03_goals.md`                  | 300–600    |
| `method_taxonomy`    | `04_method_taxonomy.md`        | 800–1500   |
| `shared_examples`    | `05_shared_examples.md`        | 500–1000   |
| `evaluation_outlook` | `98_evaluation_outlook.md`     | 1000–2000  |
| `appendices`         | `99_appendices.md`             | no floor   |

## Per-section structure
- `preface` — H1 + Purpose · Target reader · Prerequisites · Scope and limits. No citations required.
- `motivating_intro` — H1 + a real failure-mode story / practical problem (cite the source paper). Then "why this matters".
- `core_concepts` — H1 + one short subsection per `knowledge_gaps_to_explain` concept (2–4 sentences each, ending in `[arxiv:ID, node_id]` when grounded). Final subsection: list `known_concepts_assumed` with one-line pointers (no definitions).
- `goals` — H1 + bulleted reader goals (≥ 2).
- `method_taxonomy` — deterministic artifact. Always run `python -m swarn_research_mcp.research_book research_runs/{run_id} --generate`. Manual drafting is forbidden because generated references are resolved through `_paper_label` + `resolve_paper_citation`; unresolved citation metadata is surfaced in `16_book/NEEDS_REVIEW.md` rather than silently emitting `<title unknown>` / `<year unknown>` in the reader-facing book.
- `shared_examples` — H1 + 1–3 running examples (input/state/output), each citing source.
- `evaluation_outlook` — H1 + Evaluation methodology · Open problems · Future directions. Pull benchmarks/metrics from pack; pull open problems from gap report; cite limitations.
- `appendices` — deterministic artifact. Always run the generator; output is the directory `appendices/` with `glossary.md`, `notation.md`, `datasets.md`, `software.md`, `references.md` (NOT a single appendices.md file).

## Writing contract
- Book-level chapters are not generic essays. They must be grounded in the book pack and must orient the reader across the actual family/method chapters in this run.
- Do not hard-code topic boilerplate. If a claim cannot be traced to the pack, outline, gap report, or promoted paper metadata, remove it.
- `core_concepts`, `shared_examples`, and `evaluation_outlook` must cite concrete papers/nodes from the pack where grounded.
- `method_taxonomy` is a navigation chapter; it must link every family and every method. Prefer deterministic generation.
- `appendices` is a reference/glossary chapter; it must include every promoted paper. Prefer deterministic generation.
- Avoid placeholder sentences such as "This file is regenerated deterministically", "The papers in this run show...", or "remaining work is..." unless followed by concrete cited evidence.

## Hard rules
- Never re-explain anything in `pack.known_concepts_assumed`.
- Never introduce new method-level claims (defer to method chapters).
- Method-taxonomy + core-concepts links use `../families/{id}.md` and `../methods/{id}.md`.
- `preface` and `goals` have no inline-citation requirement; everything else cites when grounded.
- `method_taxonomy` and `appendices` completeness is structural, not stylistic: missing one family link or one promoted-paper reference is a form failure.

## Success
- File at canonical filename; starts with `# ` H1.
- Section-specific subsections present.
- Word count within the range.
- No generic placeholder prose, no uncited grounded claims outside `preface` and `goals`.
