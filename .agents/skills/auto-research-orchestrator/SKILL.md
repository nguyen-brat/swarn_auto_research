---
name: auto-research-orchestrator
description: Run the MVP auto-research pipeline end-to-end for one topic.
---

# Auto Research Orchestrator (MVP)

## Goal
Drive stages 0–13 in order, delegating LLM work to subagents in `.codex/agents/` and writing artifacts under `research_runs/{slug}-{ts}/`.

## Inputs
- `topic` (string, required)
- `knowledge_base_path` (default: `.agents/knowledge_base.md`)
- normal queries, survey queries, positive/negative keywords (optional; derive from topic if missing)

## MVP budgets
```
max_seed_papers       = 50
max_expansion_gaps    = 5
max_papers_per_gap    = 3
max_expansion_rounds  = 1
max_promoted_papers   = 10
chapters_written      = 1
min_gap_importance    = 0.70
min_confusion_risk    = "medium"
```

## Stage order

### Stage 0 — Create run
- Slugify topic. Create `research_runs/{slug}-{YYYYMMDD-HHMMSS}/`.
- Create the per-stage subfolders:
  `00_input 01_seed_pool 02_paper_pool 03_overviews 04_weak_evidence
   05_weak_graph 06_expansion 07_scoring 08_full_markdown 09_pageindex
   13_chapter_packs 14_chapters 15_verification 17_learning_suggestions`
- Write `run_config.json` with the budgets above plus topic and KB path.
- Write `topic.md` with the topic and any user-provided queries/keywords.
- Initialize `run_log.csv` with header `timestamp,stage,status,detail`.

### Stage 1 — Seed pool
- Call MCP `bulk_normal_start_search` with the topic queries and
  `output_dir = research_runs/{run_id}/01_seed_pool/`.
- Save results as `01_seed_pool/seed_pool_raw.json`.
- Write `02_paper_pool/paper_pool.json` (arxiv_id → record) and
  `02_paper_pool/paper_pool.csv`.
- Stop if pool < 10 papers; log and exit (topic too narrow).

### Stage 2 — Weak evidence (cheap)
- Dispatch `weak_evidence_extractor` with `arxiv_ids = paper_pool.keys()`.

### Stage 3 — Weak graph
- Dispatch `weak_graph_extractor`.

### Stage 4 — Read knowledge base
- Dispatch `knowledge_base_reader`.

### Stage 5 — Detect gaps
- Dispatch `knowledge_gap_detector`.
- Stop if `expansion_need_queue.json.items` is empty (skip Stage 6).

### Stage 6 — Expand pool (one round only)
- Skip this stage entirely if and only if `expansion_need_queue.json.items` is empty. Otherwise it is mandatory.
- Dispatch `paper_expander`.
- After it returns, validate `06_expansion/expansion_round_01.json`:
  - `status` MUST be `"completed"` (since the queue was non-empty).
  - If `status` is `"skipped"`, the agent shortcut the work. Log the failure to `run_log.csv`, then re-dispatch `paper_expander` with an explicit reminder that skipping is forbidden when the queue has items. If the second attempt also skips, stop the pipeline.
- After acceptance, dispatch `weak_evidence_extractor` AGAIN for the
  newly added arxiv_ids only.

### Stage 7 — Score and promote
- Dispatch `paper_ranker`.

### Stage 8 — Full Markdown
- For each paper in `promoted_papers.json`, call MCP `get_paper_markdown`
  and save to `08_full_markdown/{arxiv_id}.md`.
- Log each fetch in `run_log.csv`.

### Stage 9 — PageIndex
- Dispatch `paper_indexer` with the 10 promoted arxiv_ids.

### Stage 10 — Build one chapter pack (orchestrator-inline)
- Pick the largest graph community in `weak_global_graph.json` whose
  central concept is NOT in the KB (or whose central concept IS in KB
  but bridges a gap). Use it as the chapter title.
- Write `13_chapter_packs/chapter_01_pack.json`:
  ```json
  {
    "chapter_id": "chapter_01",
    "chapter_title": "<central concept>",
    "known_concepts_assumed": [<KB concepts touching this community>],
    "knowledge_gaps_to_explain": [<gap concepts mapped to this community>],
    "core_papers": [<promoted papers in community>],
    "background_papers": [<expansion papers covering the gaps>],
    "supporting_papers": [<other promoted papers cited>],
    "section_plan": [
      {"section_title": "...", "purpose": "...", "source_nodes": [...]}
    ]
  }
  ```

### Stage 11 — Write chapter
- Dispatch `chapter_writer` with `chapter_id = chapter_01`.

### Stage 12 — Verify
- Dispatch `verifier` with `chapter_id = chapter_01`.
- If `summary.claims_unsupported > 0` or `summary.gaps_missing > 0`, log
  the failure but do not auto-rewrite (MVP).
- If `summary.form_issue_count > 0` (e.g. comparison table missing,
  thin "How it works", paragraph-shaped Strengths/Limitations, abstract
  worked example, empty Implementation notes, word count below 1200),
  log the failures and re-dispatch `chapter_writer` ONCE with
  `chapter_id = chapter_01` plus the `form_issues` list as explicit
  feedback. After the rewrite, dispatch `verifier` again. If form
  issues remain after one rewrite attempt, log the final state and
  continue — do not loop indefinitely.

### Stage 13 — Learning suggestions
- Read `knowledge_gap_report.json`. List gaps that recurred across
  multiple papers. Group them under simple category headings.
- Write `17_learning_suggestions/knowledge_to_add.md`:
  ```markdown
  # Suggested Knowledge Base Additions

  Run: {run_id}

  ## <category>
  - <concept> — needed by <N> papers
  ```
- Do NOT modify `.agents/knowledge_base.md`.

## Failure handling
- On any stage failure, append a row to `run_log.csv` and stop the
  pipeline. Do not silently skip.
- Subagent return strings are logged verbatim.

## MVP success criteria
1. `run_config.json` exists.
2. `paper_pool.json` has ≥ 40 papers.
3. Every paper in `04_weak_evidence/` has non-empty `reader_needed_concepts`.
4. `knowledge_gap_report.json` has all three buckets populated.
5. Every row in `accepted_candidates.csv` has `added_for_gap` and `why_needed`.
6. `promoted_papers.json` has 10 entries each with a reason.
7. `08_full_markdown/` has 10 `.md` files.
8. `09_pageindex/trees/` has 10 valid trees.
9. `13_chapter_packs/chapter_01_pack.json` lists `known_concepts_assumed` AND `knowledge_gaps_to_explain`.
10. `14_chapters/chapter_01.md` exists, cites arXiv IDs.
11. `15_verification/chapter_01_verification.json.summary.claims_unsupported == 0`, `summary.gaps_missing == 0`, `summary.form_issue_count == 0`, and `summary.word_count >= 1200`.
12. `17_learning_suggestions/knowledge_to_add.md` exists.
